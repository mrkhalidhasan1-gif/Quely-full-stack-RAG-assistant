import os
import re
import uuid
import urllib.request
import urllib.parse
from datetime import datetime

import jwt
import pymupdf
from bson import ObjectId
from docx import Document
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from groq import Groq
from pymongo import MongoClient
from sentence_transformers import SentenceTransformer

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

load_dotenv(os.path.join(BASE_DIR, "backend", ".env"))
load_dotenv(os.path.join(BASE_DIR, "rag", ".env"), override=True)

MONGO_URI = os.getenv("MONGO_URI")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
JWT_SECRET = os.getenv("JWT_SECRET")
GROQ_MODEL = "openai/gpt-oss-120b"

if not MONGO_URI:
    raise RuntimeError("MONGO_URI is missing")
if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is missing")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET is missing")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024

mongo = MongoClient(MONGO_URI)
mongo.admin.command("ping")

db = mongo["test"]
chunks_collection = db["document_chunks"]
documents_collection = db["documents"]
chats_collection = db["chats"]

groq_client = Groq(api_key=GROQ_API_KEY)
embedding_model = SentenceTransformer("BAAI/bge-small-en-v1.5")

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
TOP_K = 8


def get_user_id():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None

    token = auth.split(" ", 1)[1]

    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = decoded.get("userId")

        if not user_id or not ObjectId.is_valid(user_id):
            return None

        return ObjectId(user_id)
    except Exception:
        return None


def clean_text(text):
    if not text:
        return ""

    text = text.replace("\xa0", " ").replace("\r", "\n")
    text = re.sub(r"(?<=[A-Za-z])\n(?=[a-z])", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def extract_document(file_path):
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        pdf = pymupdf.open(file_path)
        pages = []

        for number, page in enumerate(pdf, start=1):
            pages.append({
                "page": number,
                "text": clean_text(page.get_text("text"))
            })

        pdf.close()
        return pages

    if ext == ".docx":
        doc = Document(file_path)
        text = "\n".join(
            p.text.strip()
            for p in doc.paragraphs
            if p.text.strip()
        )
        return [{"page": 1, "text": clean_text(text)}]

    if ext == ".txt":
        with open(file_path, "r", encoding="utf-8", errors="ignore") as file:
            return [{"page": 1, "text": clean_text(file.read())}]

    raise ValueError("Unsupported document type")


def split_text(text, page, section="General", size=800, overlap=200):
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return []

    words = text.split()
    chunks = []
    current = []

    for word in words:
        candidate = " ".join(current + [word])

        if len(candidate) <= size:
            current.append(word)
        else:
            if current:
                chunks.append({
                    "text": f"Section: {section}\n{' '.join(current)}",
                    "page": page,
                    "section": section
                })

            overlap_text = " ".join(current)[-overlap:]
            keep = overlap_text.split() if overlap_text else []
            current = keep + [word]

    if current:
        chunks.append({
            "text": f"Section: {section}\n{' '.join(current)}",
            "page": page,
            "section": section
        })

    return chunks


def create_chunks(pages):
    chunks = []

    for page in pages:
        text = page["text"]
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        section = "General"
        section_text = []

        for line in lines:
            is_heading = (
                line.isupper()
                or bool(re.match(r"^(Chapter|Section|Part|Topic)\s+\d+", line, re.I))
            )

            if is_heading:
                if section_text:
                    chunks.extend(
                        split_text(
                            " ".join(section_text),
                            page["page"],
                            section
                        )
                    )
                    section_text = []

                section = line
            else:
                section_text.append(line)

        if section_text:
            chunks.extend(
                split_text(
                    " ".join(section_text),
                    page["page"],
                    section
                )
            )

    return chunks


def save_document(document_id, user_id, name, source):
    documents_collection.update_one(
        {"documentId": document_id},
        {
            "$set": {
                "documentId": document_id,
                "userId": user_id,
                "name": name,
                "source": source,
                "updatedAt": datetime.utcnow()
            },
            "$setOnInsert": {
                "createdAt": datetime.utcnow()
            }
        },
        upsert=True
    )


def save_chunks(document_id, user_id, name, chunks):
    if not chunks:
        raise ValueError("No readable content found")

    texts = [chunk["text"] for chunk in chunks]

    embeddings = embedding_model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False
    )

    chunks_collection.delete_many({
        "documentId": document_id
    })

    docs = []

    for chunk, embedding in zip(chunks, embeddings):
        docs.append({
            "documentId": document_id,
            "userId": user_id,
            "documentName": name,
            "text": chunk["text"],
            "page": chunk["page"],
            "section": chunk["section"],
            "embedding": embedding.tolist()
        })

    chunks_collection.insert_many(docs)

    return len(docs)


def retrieve(question, document_id, user_id=None):
    query = (
        "Represent this sentence for searching relevant passages: "
        + question
    )

    vector = embedding_model.encode(
        query,
        normalize_embeddings=True
    ).tolist()

    filters = [
        {
            "documentId": {
                "$eq": document_id
            }
        }
    ]

    if user_id:
        filters.append({
            "userId": {
                "$eq": user_id
            }
        })

    search_filter = filters[0] if len(filters) == 1 else {
        "$and": filters
    }

    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": vector,
                "numCandidates": 160,
                "limit": TOP_K,
                "filter": search_filter
            }
        },
        {
            "$project": {
                "_id": 0,
                "text": 1,
                "page": 1,
                "section": 1,
                "score": {
                    "$meta": "vectorSearchScore"
                }
            }
        }
    ]

    return list(
        chunks_collection.aggregate(pipeline)
    )


def generate_answer(question, results):
    if not results:
        return "I couldn't find relevant information in the provided document."

    context = "\n\n".join(
        f"[Source {i}]\n"
        f"Page: {result['page']}\n"
        f"Section: {result['section']}\n"
        f"Content:\n{result['text']}"
        for i, result in enumerate(results, 1)
    )

    system_prompt = """You are Quely, a RAG-based document assistant.
Answer using ONLY the retrieved document context.
Do not use outside knowledge.
Do not invent facts.
If the answer is not supported by the context, say:
"I couldn't find this information in the provided document."
Keep answers clear and concise.
Mention page numbers when useful."""

    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": (
                    f"Retrieved document context:\n\n{context}"
                    f"\n\nQuestion:\n{question}"
                )
            }
        ],
        temperature=0.2,
        max_tokens=500
    )

    return response.choices[0].message.content.strip()


def save_chat(user_id, document_id, document_name, question, answer, sources):
    if not user_id:
        return

    now = datetime.utcnow()

    user_message = {
        "role": "user",
        "content": question
    }

    assistant_message = {
        "role": "assistant",
        "content": answer,
        "sources": sources
    }

    chat = chats_collection.find_one({
        "userId": user_id,
        "documentId": document_id
    })

    if not chat:
        chats_collection.insert_one({
            "userId": user_id,
            "documentId": document_id,
            "title": question[:60],
            "documentName": document_name,
            "documentPath": document_id,
            "messages": [
                user_message,
                assistant_message
            ],
            "createdAt": now,
            "updatedAt": now
        })
    else:
        chats_collection.update_one(
            {"_id": chat["_id"]},
            {
                "$push": {
                    "messages": {
                        "$each": [
                            user_message,
                            assistant_message
                        ]
                    }
                },
                "$set": {
                    "updatedAt": now
                }
            }
        )


@app.route("/api/rag/upload", methods=["POST"])
def upload():
    user_id = get_user_id()

    if request.headers.get("Authorization") and not user_id:
        return jsonify({
            "message": "Invalid or expired token"
        }), 401

    file = request.files.get("document")

    if not file:
        return jsonify({
            "message": "Please upload a document"
        }), 400

    ext = os.path.splitext(file.filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({
            "message": "Only PDF, DOCX and TXT files are supported"
        }), 400

    document_id = request.form.get("documentId") or str(uuid.uuid4())
    document_name = file.filename
    temp_path = f"/tmp/quely-{uuid.uuid4()}{ext}"

    try:
        file.save(temp_path)

        pages = extract_document(temp_path)
        chunks = create_chunks(pages)

        count = save_chunks(
            document_id,
            user_id,
            document_name,
            chunks
        )

        save_document(
            document_id,
            user_id,
            document_name,
            "upload"
        )

        return jsonify({
            "message": "Document processed successfully.",
            "documentId": document_id,
            "documentName": document_name,
            "chunks": count
        })

    except Exception as error:
        print("Upload error:", error)
        return jsonify({
            "message": "Unable to process document."
        }), 500

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def process_website(url, user_id):
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Invalid website URL")

    request_obj = urllib.request.Request(
        url,
        headers={"User-Agent": "Quely/1.0"}
    )

    with urllib.request.urlopen(
        request_obj,
        timeout=15
    ) as response:
        html = response.read(
            3_000_000
        ).decode(
            "utf-8",
            errors="ignore"
        )

    text = re.sub(
        r"<script[\s\S]*?</script>",
        " ",
        html,
        flags=re.I
    )

    text = re.sub(
        r"<style[\s\S]*?</style>",
        " ",
        text,
        flags=re.I
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    if not text:
        raise ValueError("No readable content found on website")

    document_id = str(uuid.uuid4())
    document_name = parsed.hostname or "Website"

    chunks = create_chunks([
        {
            "page": 1,
            "text": text
        }
    ])

    count = save_chunks(
        document_id,
        user_id,
        document_name,
        chunks
    )

    save_document(
        document_id,
        user_id,
        document_name,
        url
    )

    return {
        "message": "Website processed successfully.",
        "documentId": document_id,
        "documentName": document_name,
        "chunks": count
    }


@app.route("/api/rag/website", methods=["POST"])
def website():
    user_id = get_user_id()

    if not user_id:
        return jsonify({
            "message": "Authentication required"
        }), 401

    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "")).strip()

    try:
        return jsonify(
            process_website(url, user_id)
        )
    except Exception as error:
        print("Website error:", error)
        return jsonify({
            "message": str(error)
        }), 400


@app.route("/api/rag/ask", methods=["POST"])
def ask():
    user_id = get_user_id()
    data = request.get_json(silent=True) or {}

    document_id = data.get("documentId")
    question = str(
        data.get("question", "")
    ).strip()

    document_name = data.get(
        "documentName",
        "Document"
    )

    if not document_id or not question:
        return jsonify({
            "message": "Document and question are required."
        }), 400

    if not user_id:
        return jsonify({
            "message": "Authentication required"
        }), 401

    try:
        results = retrieve(
            question,
            document_id,
            user_id
        )

        answer = generate_answer(
            question,
            results
        )

        sources = [
            {
                "page": result["page"],
                "section": result["section"],
                "score": result.get("score", 0)
            }
            for result in results
        ]

        save_chat(
            user_id,
            document_id,
            document_name,
            question,
            answer,
            sources
        )

        return jsonify({
            "answer": answer,
            "sources": sources
        })

    except Exception as error:
        print("Ask error:", error)
        return jsonify({
            "message": "Unable to generate answer."
        }), 500


@app.route("/api/rag/guest-upload", methods=["POST"])
def guest_upload():
    return upload()


@app.route("/api/rag/guest-website", methods=["POST"])
def guest_website():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "")).strip()

    try:
        return jsonify(
            process_website(url, None)
        )
    except Exception as error:
        print("Guest website error:", error)
        return jsonify({
            "message": str(error)
        }), 400


@app.route("/api/rag/guest-ask", methods=["POST"])
def guest_ask():
    data = request.get_json(silent=True) or {}

    document_id = data.get("documentId")
    question = str(
        data.get("question", "")
    ).strip()

    if not document_id or not question:
        return jsonify({
            "message": "Document and question are required."
        }), 400

    try:
        results = retrieve(
            question,
            document_id
        )

        answer = generate_answer(
            question,
            results
        )

        sources = [
            {
                "page": result["page"],
                "section": result["section"],
                "score": result.get("score", 0)
            }
            for result in results
        ]

        return jsonify({
            "answer": answer,
            "sources": sources
        })

    except Exception as error:
        print("Guest ask error:", error)
        return jsonify({
            "message": "Unable to generate answer."
        }), 500


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=8000,
        debug=True
    )