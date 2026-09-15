import os

os.environ["HF_HOME"] = "/tmp/huggingface"
os.environ["HF_HUB_CACHE"] = "/tmp/huggingface/hub"
os.environ["HF_XET_CACHE"] = "/tmp/huggingface/xet"
os.environ["HF_ASSETS_CACHE"] = "/tmp/huggingface/assets"
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["XDG_CACHE_HOME"] = "/tmp/cache"
os.environ["FASTEMBED_CACHE_PATH"] = "/tmp/fastembed"

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
from fastembed import TextEmbedding

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
embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5", cache_dir="/tmp/fastembed")

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
TOP_K = 8

def get_user_id():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        decoded = jwt.decode(auth.split(" ", 1)[1], JWT_SECRET, algorithms=["HS256"])
        return str(decoded["userId"])
    except Exception:
        return None

def object_id(user_id):
    try:
        return ObjectId(user_id) if user_id else None
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
        pages = [{"page": i, "text": clean_text(page.get_text("text"))} for i, page in enumerate(pdf, 1)]
        pdf.close()
        return pages
    if ext == ".docx":
        doc = Document(file_path)
        text = "\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())
        return [{"page": 1, "text": clean_text(text)}]
    if ext == ".txt":
        with open(file_path, "r", encoding="utf-8", errors="ignore") as file:
            return [{"page": 1, "text": clean_text(file.read())}]
    raise ValueError("Unsupported document type")

def split_text(text, page, section="General", size=800, overlap=200):
    words = re.sub(r"\s+", " ", text).strip().split()
    chunks = []
    current = []
    for word in words:
        candidate = " ".join(current + [word])
        if len(candidate) <= size:
            current.append(word)
        else:
            if current:
                chunks.append({"text": f"Section: {section}\n{' '.join(current)}", "page": page, "section": section})
            overlap_words = " ".join(current)[-overlap:].split()
            current = overlap_words + [word]
    if current:
        chunks.append({"text": f"Section: {section}\n{' '.join(current)}", "page": page, "section": section})
    return chunks

def create_chunks(pages):
    chunks = []
    for page in pages:
        lines = [line.strip() for line in page["text"].splitlines() if line.strip()]
        section = "General"
        section_text = []
        for line in lines:
            heading = line.isupper() or bool(re.match(r"^(Chapter|Section|Part|Topic)\s+\d+", line, re.I))
            if heading:
                if section_text:
                    chunks.extend(split_text(" ".join(section_text), page["page"], section))
                    section_text = []
                section = line
            else:
                section_text.append(line)
        if section_text:
            chunks.extend(split_text(" ".join(section_text), page["page"], section))
    return chunks

def save_document(document_id, user_id, name, source):
    documents_collection.update_one(
        {"documentId": document_id},
        {"$set": {
            "documentId": document_id,
            "userId": object_id(user_id),
            "name": name,
            "source": source
        }},
        upsert=True
    )

def save_chunks(document_id, user_id, name, chunks):
    if not chunks:
        raise ValueError("No readable content found")
    texts = [chunk["text"] for chunk in chunks]
    embeddings = list(embedding_model.embed(texts))
    docs = []
    for chunk, embedding in zip(chunks, embeddings):
        docs.append({
            "documentId": document_id,
            "userId": object_id(user_id),
            "documentName": name,
            "text": chunk["text"],
            "page": chunk["page"],
            "section": chunk["section"],
            "embedding": embedding.tolist()
        })
    chunks_collection.delete_many({"documentId": document_id})
    chunks_collection.insert_many(docs)
    return len(docs)

def retrieve(question, document_id, user_id=None):
    query = "Represent this sentence for searching relevant passages: " + question
    vector = list(embedding_model.embed([query]))[0].tolist()
    search_filter = {"documentId": {"$eq": document_id}}
    if user_id:
        uid = object_id(user_id)
        if uid:
            search_filter = {"$and": [
                {"documentId": {"$eq": document_id}},
                {"userId": {"$eq": uid}}
            ]}
    pipeline = [
        {"$vectorSearch": {
            "index": "vector_index",
            "path": "embedding",
            "queryVector": vector,
            "numCandidates": 160,
            "limit": TOP_K,
            "filter": search_filter
        }},
        {"$project": {
            "_id": 0,
            "text": 1,
            "page": 1,
            "section": 1,
            "score": {"$meta": "vectorSearchScore"}
        }}
    ]
    return list(chunks_collection.aggregate(pipeline))

def generate_answer(question, results):
    if not results:
        return "I couldn't find relevant information in the provided document."
    context = "\n\n".join(
        f"[Source {i}]\nPage: {r['page']}\nSection: {r['section']}\nContent:\n{r['text']}"
        for i, r in enumerate(results, 1)
    )
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {
                "role": "system",
                "content": """You are Quely, a RAG-based document assistant.
Answer using ONLY the retrieved document context.
Do not use outside knowledge.
Do not invent facts.
If the answer is not supported by the context, say:
"I couldn't find this information in the provided document."
Keep answers clear and concise.
Mention page numbers when useful."""
            },
            {"role": "user", "content": f"Retrieved document context:\n\n{context}\n\nQuestion:\n{question}"}
        ],
        temperature=0.2,
        max_tokens=500
    )
    return response.choices[0].message.content.strip()

def save_chat(user_id, document_id, document_name, question, answer, sources):
    uid = object_id(user_id)
    if not uid:
        return
    chat = chats_collection.find_one({"userId": uid, "documentId": document_id})
    messages = [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer, "sources": sources}
    ]
    now = datetime.utcnow()
    if not chat:
        chats_collection.insert_one({
            "userId": uid,
            "documentId": document_id,
            "title": question[:60],
            "documentName": document_name,
            "documentPath": document_id,
            "messages": messages,
            "createdAt": now,
            "updatedAt": now
        })
    else:
        chats_collection.update_one(
            {"_id": chat["_id"]},
            {"$push": {"messages": {"$each": messages}}, "$set": {"updatedAt": now}}
        )

def fetch_website(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Invalid website URL")
    req = urllib.request.Request(url, headers={"User-Agent": "Quely/1.0"})
    with urllib.request.urlopen(req, timeout=15) as response:
        html = response.read(1_000_000).decode("utf-8", errors="ignore")
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    text = text[:50000]
    if not text:
        raise ValueError("No readable content found on website")
    return parsed, text

def process_website(url, user_id):
    parsed, text = fetch_website(url)
    document_id = str(uuid.uuid4())
    name = parsed.hostname or "Website"
    chunks = create_chunks([{"page": 1, "text": text}])
    count = save_chunks(document_id, user_id, name, chunks)
    save_document(document_id, user_id, name, url)
    return document_id, name, count

@app.route("/api/rag/upload", methods=["POST"])
def upload():
    user_id = get_user_id()
    if request.headers.get("Authorization") and not user_id:
        return jsonify({"message": "Invalid or expired token"}), 401
    file = request.files.get("document")
    if not file:
        return jsonify({"message": "Please upload a document"}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"message": "Only PDF, DOCX and TXT files are supported"}), 400
    document_id = request.form.get("documentId") or str(uuid.uuid4())
    name = file.filename
    temp_path = f"/tmp/quely-{uuid.uuid4()}{ext}"
    try:
        file.save(temp_path)
        chunks = create_chunks(extract_document(temp_path))
        count = save_chunks(document_id, user_id, name, chunks)
        save_document(document_id, user_id, name, "upload")
        return jsonify({"message": "Document processed successfully.", "documentId": document_id, "documentName": name, "chunks": count})
    except Exception as error:
        print("Upload error:", error)
        return jsonify({"message": "Unable to process document."}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.route("/api/rag/website", methods=["POST"])
def website():
    user_id = get_user_id()
    if not user_id:
        return jsonify({"message": "Authentication required"}), 401
    try:
        document_id, name, count = process_website(str((request.get_json(silent=True) or {}).get("url", "")).strip(), user_id)
        return jsonify({"message": "Website processed successfully.", "documentId": document_id, "documentName": name, "chunks": count})
    except Exception as error:
        print("Website error:", error)
        return jsonify({"message": str(error)}), 400

@app.route("/api/rag/guest-upload", methods=["POST"])
def guest_upload():
    return upload()

@app.route("/api/rag/guest-website", methods=["POST"])
def guest_website():
    try:
        document_id, name, count = process_website(str((request.get_json(silent=True) or {}).get("url", "")).strip(), None)
        return jsonify({"message": "Website processed successfully.", "documentId": document_id, "documentName": name, "chunks": count})
    except Exception as error:
        print("Guest website error:", error)
        return jsonify({"message": str(error)}), 400

@app.route("/api/rag/ask", methods=["POST"])
def ask():
    user_id = get_user_id()
    data = request.get_json(silent=True) or {}
    document_id = data.get("documentId")
    question = str(data.get("question", "")).strip()
    document_name = data.get("documentName", "Document")
    if not document_id or not question:
        return jsonify({"message": "Document and question are required."}), 400
    if data.get("authenticated") and not user_id:
        return jsonify({"message": "Authentication required"}), 401
    try:
        results = retrieve(question, document_id, user_id)
        answer = generate_answer(question, results)
        sources = [{"page": r["page"], "section": r["section"], "score": r.get("score", 0)} for r in results]
        if user_id:
            save_chat(user_id, document_id, document_name, question, answer, sources)
        return jsonify({"answer": answer, "sources": sources})
    except Exception as error:
        print("Ask error:", error)
        return jsonify({"message": "Unable to generate answer."}), 500

@app.route("/api/rag/guest-ask", methods=["POST"])
def guest_ask():
    data = request.get_json(silent=True) or {}
    document_id = data.get("documentId")
    question = str(data.get("question", "")).strip()
    if not document_id or not question:
        return jsonify({"message": "Document and question are required."}), 400
    try:
        results = retrieve(question, document_id)
        answer = generate_answer(question, results)
        sources = [{"page": r["page"], "section": r["section"], "score": r.get("score", 0)} for r in results]
        return jsonify({"answer": answer, "sources": sources})
    except Exception as error:
        print("Guest ask error:", error)
        return jsonify({"message": "Unable to generate answer."}), 500

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Quely RAG API is running"})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)