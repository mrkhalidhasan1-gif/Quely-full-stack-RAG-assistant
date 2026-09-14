import os
import re
import sys
import numpy as np
import pymongo
import pymupdf
from dotenv import load_dotenv
from docx import Document
from groq import Groq
from sentence_transformers import SentenceTransformer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ENV_PATH = os.path.join(BASE_DIR, "..", "backend", ".env")
ENV_PATH = os.path.join(BASE_DIR, ".env")

load_dotenv(BACKEND_ENV_PATH)
load_dotenv(ENV_PATH, override=True)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
GROQ_MODEL = "openai/gpt-oss-120b"
MONGO_DB = os.getenv("MONGO_DB", "test")
MONGO_COLLECTION = "document_chunks"

CHUNK_SIZE = 800
OVERLAP = 200
TOP_K = 8
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
VECTOR_INDEX = "vector_index"

DOCUMENT_PATH = sys.argv[1] if len(sys.argv) > 1 else None
DOCUMENT_ID = os.path.basename(DOCUMENT_PATH) if DOCUMENT_PATH else None

if not GROQ_API_KEY:
    print("ERROR: GROQ_API_KEY is missing.")
    sys.exit(1)

if not MONGO_URI:
    print("ERROR: MONGO_URI is missing.")
    sys.exit(1)

try:
    groq_client = Groq(api_key=GROQ_API_KEY)
    mongo_client = pymongo.MongoClient(MONGO_URI)
    mongo_client.admin.command("ping")
    chunks_collection = mongo_client[MONGO_DB][MONGO_COLLECTION]
except Exception as error:
    print("Database/client initialization failed:")
    print(error)
    sys.exit(1)

_embedding_model = None

def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        print("Loading embedding model...")
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL)
    return _embedding_model

def clean_text(text):
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = text.replace("\r", "\n")
    text = re.sub(r"(?<=[A-Za-z])\n(?=[a-z])", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def extract_pdf(pdf_path):
    doc = pymupdf.open(pdf_path)
    pages = []
    for page_number, page in enumerate(doc, start=1):
        pages.append({"page": page_number, "text": clean_text(page.get_text("text"))})
    doc.close()
    return pages

def extract_document(file_path):
    extension = os.path.splitext(file_path)[1].lower()

    if extension == ".pdf":
        return extract_pdf(file_path)

    if extension == ".docx":
        document = Document(file_path)
        text = [p.text.strip() for p in document.paragraphs if p.text.strip()]
        return [{"page": 1, "text": clean_text("\n".join(text))}]

    if extension == ".txt":
        with open(file_path, "r", encoding="utf-8", errors="ignore") as file:
            text = file.read()
        return [{"page": 1, "text": clean_text(text)}]

    raise ValueError(f"Unsupported document type: {extension}")

def is_heading(line):
    line = line.strip()
    if not line:
        return False

    words = line.split()
    if len(words) > 10:
        return False

    if line.isupper():
        return True

    if re.match(r"^(?:Chapter|Section|Part|Topic)\s+\d+.*$", line, flags=re.I):
        return True

    if re.match(r"^\d+(\.\d+)*\s+[A-Z].*$", line):
        return True

    if re.match(r"^[A-Z][A-Za-z0-9&/:-]+(?:\s+[A-Z][A-Za-z0-9&/:-]+){0,7}$", line):
        return True

    return False

def split_section(text, section, page_number):
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    parts = re.split(r"(?<=[.!?])\s+", text)
    parts = [part.strip() for part in parts if part.strip()]

    chunks = []
    current = ""

    for part in parts:
        if len(current) + len(part) + 1 <= CHUNK_SIZE:
            current = current + " " + part if current else part
        else:
            if current:
                chunks.append({
                    "text": f"Section: {section}\n{current}",
                    "page": page_number,
                    "section": section
                })

            if len(part) > CHUNK_SIZE:
                words = part.split()
                temp = ""

                for word in words:
                    if len(temp) + len(word) + 1 <= CHUNK_SIZE:
                        temp = temp + " " + word if temp else word
                    else:
                        if temp:
                            chunks.append({
                                "text": f"Section: {section}\n{temp}",
                                "page": page_number,
                                "section": section
                            })
                        temp = word

                current = temp
            else:
                current = part

    if current:
        chunks.append({
            "text": f"Section: {section}\n{current}",
            "page": page_number,
            "section": section
        })

    if len(chunks) > 1:
        for i in range(len(chunks) - 1):
            overlap_text = chunks[i]["text"][-OVERLAP:]
            chunks[i + 1]["text"] = overlap_text + " " + chunks[i + 1]["text"]

    return chunks

def create_chunks(pages):
    chunks = []

    for page in pages:
        page_number = page["page"]
        raw_text = page["text"]
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

        current_section = "General"
        section_text = []

        for line in lines:
            if is_heading(line):
                if section_text:
                    joined_text = " ".join(section_text)
                    chunks.extend(split_section(joined_text, current_section, page_number))
                    section_text = []
                current_section = line
            else:
                section_text.append(line)

        if section_text:
            joined_text = " ".join(section_text)
            chunks.extend(split_section(joined_text, current_section, page_number))

    return chunks

def create_embeddings(chunks):
    model = get_embedding_model()
    texts = [chunk["text"] for chunk in chunks]

    print("Creating embeddings...")

    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True
    )

    return model, np.asarray(embeddings, dtype=np.float32)

def save_vectors(chunks, embeddings, document_id=None, user_id=None, document_name=""):
    if not document_id:
        document_id = DOCUMENT_ID

    if not document_id:
        raise ValueError("Document ID is required.")

    chunks_collection.delete_many({"documentId": document_id})

    data = []

    for chunk, embedding in zip(chunks, embeddings):
        data.append({
            "documentId": document_id,
            "userId": user_id,
            "documentName": document_name,
            "text": chunk["text"],
            "page": chunk["page"],
            "section": chunk["section"],
            "embedding": embedding.tolist()
        })

    if data:
        chunks_collection.insert_many(data)

    print(f"{len(data)} chunks saved to MongoDB.")

def load_vectors(document_id=None):
    document_id = document_id or DOCUMENT_ID

    if not document_id:
        return None

    try:
        data = list(
            chunks_collection.find(
                {"documentId": document_id},
                {
                    "_id": 0,
                    "documentId": 1,
                    "userId": 1,
                    "documentName": 1,
                    "text": 1,
                    "page": 1,
                    "section": 1,
                    "embedding": 1
                }
            )
        )

        return data if data else None
    except Exception as error:
        print("MongoDB vector load error:")
        print(error)
        return None

def search(question, model, chunks=None, embeddings=None, top_k=TOP_K, document_id=None, user_id=None):
    question = question.strip()

    if not question:
        return []

    document_id = document_id or DOCUMENT_ID

    if not document_id:
        return []

    query = "Represent this sentence for searching relevant passages: " + question
    query_embedding = model.encode(query, normalize_embeddings=True).tolist()

    filters = [{"documentId": {"$eq": document_id}}]

    if user_id:
        filters.append({"userId": {"$eq": user_id}})

    vector_filter = filters[0] if len(filters) == 1 else {"$and": filters}

    pipeline = [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX,
                "path": "embedding",
                "queryVector": query_embedding,
                "numCandidates": max(top_k * 10, 100),
                "limit": top_k,
                "filter": vector_filter
            }
        },
        {
            "$project": {
                "_id": 0,
                "text": 1,
                "page": 1,
                "section": 1,
                "documentId": 1,
                "score": {"$meta": "vectorSearchScore"}
            }
        }
    ]

    try:
        results = list(chunks_collection.aggregate(pipeline))

        return [
            {
                "score": float(result.get("score", 0)),
                "text": result.get("text", ""),
                "page": result.get("page", 1),
                "section": result.get("section", "General")
            }
            for result in results
        ]
    except Exception as error:
        print("MongoDB Vector Search error:")
        print(error)
        return []

def summarize_document(chunks):
    print("\nGenerating document summary...")

    if not chunks:
        return "I couldn't find any content in the document."

    context_parts = []

    for index, chunk in enumerate(chunks, start=1):
        context_parts.append(
            f"[Section {index}]\n"
            f"Page: {chunk['page']}\n"
            f"Section: {chunk['section']}\n"
            f"Content:\n{chunk['text']}"
        )

    context = "\n\n".join(context_parts)

    system_prompt = """
You are Quely, a RAG-based document assistant.

Summarize the provided document using ONLY the document content.

Rules:
1. Do not use outside knowledge.
2. Do not invent information.
3. Cover the important points from the entire document.
4. Keep the summary clear and well structured.
5. Mention important projects, skills, technologies, education, experience, or contact information when present.
6. If something is not present, do not add it.
"""

    user_prompt = f"""
Document content:

{context}

Create a concise but complete summary of this document.
"""

    try:
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            max_tokens=800
        )

        answer = response.choices[0].message.content

        if answer:
            return answer.strip()

        return "I couldn't generate a summary."

    except Exception as error:
        print("\nGroq error:")
        print(error)
        return "Sorry, I couldn't generate a summary right now."

def generate_answer(question, results):
    print("\nGenerating answer...")

    if not results:
        return "I couldn't find relevant information in the provided document."

    context_parts = []

    for index, result in enumerate(results, start=1):
        context_parts.append(
            f"[Source {index}]\n"
            f"Page: {result['page']}\n"
            f"Section: {result['section']}\n"
            f"Content:\n{result['text']}"
        )

    context = "\n\n".join(context_parts)

    system_prompt = """
You are Quely, a RAG-based document assistant.

Your job is to answer questions using ONLY the retrieved document context provided by the user.

Rules:
1. Use only the retrieved context.
2. Do not use outside knowledge.
3. Do not invent facts.
4. If the answer is not supported by the context, say:
   "I couldn't find this information in the provided document."
5. Keep answers clear and concise.
6. Mention page numbers when useful.
7. If multiple sources support the answer, combine them naturally.
"""

    user_prompt = f"""
Retrieved document context:

{context}

User question:

{question}
"""

    try:
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            max_tokens=500
        )

        answer = response.choices[0].message.content

        if answer:
            return answer.strip()

        return "I couldn't generate an answer."

    except Exception as error:
        print("\nGroq error:")
        print(error)
        return "Sorry, I couldn't generate an answer right now."

if __name__ == "__main__":
    if not DOCUMENT_PATH:
        print("Please provide a document path.")
        sys.exit(1)

    process_only = "--process-only" in sys.argv

    print("Checking MongoDB for saved vectors...")

    saved = load_vectors()

    if saved:
        print("Loaded saved vectors from MongoDB.")

        chunks = [
            {
                "text": item["text"],
                "page": item["page"],
                "section": item["section"]
            }
            for item in saved
        ]

        model = get_embedding_model()

    else:
        print("Extracting document text...")

        try:
            pages = extract_document(DOCUMENT_PATH)
        except Exception as error:
            print(f"Document extraction failed: {error}")
            sys.exit(1)

        print(f"Pages extracted: {len(pages)}")

        print("Creating chunks...")
        chunks = create_chunks(pages)
        print(f"Chunks created: {len(chunks)}")

        for index, chunk in enumerate(chunks[:5], start=1):
            print(f"Chunk {index} | Page {chunk['page']} | {chunk['section']}")
            print(chunk["text"][:220])
            print()

        model, embeddings = create_embeddings(chunks)

        save_vectors(
            chunks,
            embeddings,
            document_id=DOCUMENT_ID
        )

    print("\n--------------------------------")
    print("RAG retrieval + MongoDB Vector Search + Groq ready.")
    print("--------------------------------")

    if process_only:
        print("Document processing completed.")
        sys.exit(0)

    while True:
        question = input("\nAsk a question: ")

        if question.lower() == "exit":
            break

        if "summar" in question.lower():
            answer = summarize_document(chunks)
        else:
            results = search(
                question,
                model,
                document_id=DOCUMENT_ID
            )
            answer = generate_answer(question, results)

        print("\nAnswer:")
        print(answer)