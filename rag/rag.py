import json
import os
import re
import sys

import numpy as np
import pymupdf
from dotenv import load_dotenv
from docx import Document
from groq import Groq
from sentence_transformers import SentenceTransformer


# ==========================================
# CONFIGURATION
# ==========================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")

load_dotenv(dotenv_path=ENV_PATH)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "openai/gpt-oss-120b"

CHUNK_SIZE = 800
OVERLAP = 200
TOP_K = 8


# ==========================================
# DOCUMENT PATH
# ==========================================

if len(sys.argv) > 1:
    DOCUMENT_PATH = sys.argv[1]
else:
    print("Please provide a document path.")
    print("Example:")
    print('python3 rag.py "/tmp/quely-uploads/file.pdf"')
    sys.exit(1)


# Every uploaded document gets its own vector file
upload_id = os.path.basename(DOCUMENT_PATH)
VECTOR_PATH = os.path.join(BASE_DIR, f"vectors_{upload_id}.json")


# ==========================================
# GROQ CLIENT
# ==========================================

if not GROQ_API_KEY:
    print("ERROR: GROQ_API_KEY is missing from .env")
    sys.exit(1)

try:
    groq_client = Groq(api_key=GROQ_API_KEY)
except Exception as error:
    print("Groq client initialization failed:")
    print(error)
    sys.exit(1)


# ==========================================
# 1. CLEAN TEXT
# ==========================================

def clean_text(text):
    if not text:
        return ""

    text = text.replace("\xa0", " ")
    text = text.replace("\r", "\n")

    # Join words broken by PDF line wrapping
    text = re.sub(r"(?<=[A-Za-z])\n(?=[a-z])", "", text)

    # Keep paragraph/line boundaries for heading detection
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# ==========================================
# 2. EXTRACT PDF
# ==========================================

def extract_pdf(pdf_path):
    doc = pymupdf.open(pdf_path)
    pages = []

    for page_number, page in enumerate(doc, start=1):
        raw_text = page.get_text("text")
        pages.append({"page": page_number, "text": clean_text(raw_text)})

    doc.close()
    return pages


# ==========================================
# 3. EXTRACT DOCX / TXT / WEBSITE
# ==========================================

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


# ==========================================
# 4. HEADING DETECTION
# ==========================================

def is_heading(line):
    line = line.strip()

    if not line:
        return False

    words = line.split()

    if len(words) > 10:
        return False

    # Example: PERSONAL PROJECTS
    if line.isupper():
        return True

    # Example: Chapter 1 / Section 2
    if re.match(r"^(?:Chapter|Section|Part|Topic)\s+\d+.*$", line, flags=re.I):
        return True

    # Example: 1. Introduction / 2.1 Experience
    if re.match(r"^\d+(\.\d+)*\s+[A-Z].*$", line):
        return True

    # Example: Professional Summary / Technical Skills
    if re.match(r"^[A-Z][A-Za-z0-9&/:-]+(?:\s+[A-Z][A-Za-z0-9&/:-]+){0,7}$", line):
        return True

    return False


# ==========================================
# 5. CHUNK CREATION
# ==========================================

def split_section(text, section, page_number):
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return []

    # Split around sentences
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

            # If one sentence itself is too large
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

    # Add overlap
    if len(chunks) > 1:
        for i in range(len(chunks) - 1):
            current_text = chunks[i]["text"]
            overlap_text = current_text[-OVERLAP:]
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


# ==========================================
# 6. EMBEDDINGS
# ==========================================

def create_embeddings(chunks):
    print("Loading embedding model...")

    model = SentenceTransformer("BAAI/bge-small-en-v1.5")

    texts = [chunk["text"] for chunk in chunks]

    print("Creating embeddings...")

    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True
    )

    return model, np.asarray(embeddings, dtype=np.float32)


# ==========================================
# 7. SAVE VECTORS
# ==========================================

def save_vectors(chunks, embeddings):
    data = []

    for chunk, embedding in zip(chunks, embeddings):
        data.append({
            "text": chunk["text"],
            "page": chunk["page"],
            "section": chunk["section"],
            "embedding": embedding.tolist()
        })

    with open(VECTOR_PATH, "w", encoding="utf-8") as file:
        json.dump(data, file)

    print("Vectors saved successfully.")


# ==========================================
# 8. LOAD VECTORS
# ==========================================

def load_vectors():
    if not os.path.exists(VECTOR_PATH):
        return None

    try:
        with open(VECTOR_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)

        return data if data else None

    except Exception:
        return None


# ==========================================
# 9. SEMANTIC SEARCH
# ==========================================

def search(question, model, chunks, embeddings, top_k=TOP_K):
    question = question.strip()

    if not question:
        return []

    # BGE query instruction
    query = "Represent this sentence for searching relevant passages: " + question

    query_embedding = model.encode(query, normalize_embeddings=True)

    # Cosine similarity because embeddings are normalized
    scores = embeddings @ query_embedding

    ranked = []

    for index, score in enumerate(scores):
        ranked.append({
            "score": float(score),
            "text": chunks[index]["text"],
            "page": chunks[index]["page"],
            "section": chunks[index]["section"]
        })

    ranked.sort(key=lambda item: item["score"], reverse=True)

    return ranked[:top_k]


# ==========================================
# 10. SUMMARIZE DOCUMENT
# ==========================================

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


# ==========================================
# 11. GROQ ANSWER GENERATION
# ==========================================

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


# ==========================================
# 12. MAIN
# ==========================================

if __name__ == "__main__":
    process_only = "--process-only" in sys.argv

    print("Checking saved vectors...")

    saved = load_vectors()

    if saved:
        print("Loaded saved vectors from file.")

        chunks = [
            {
                "text": item["text"],
                "page": item["page"],
                "section": item["section"]
            }
            for item in saved
        ]

        embeddings = np.asarray(
            [item["embedding"] for item in saved],
            dtype=np.float32
        )

        print("Loading embedding model...")
        model = SentenceTransformer("BAAI/bge-small-en-v1.5")

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
            print(
                f"Chunk {index} | Page {chunk['page']} | {chunk['section']}"
            )
            print(chunk["text"][:220])
            print()

        model, embeddings = create_embeddings(chunks)
        save_vectors(chunks, embeddings)

    print("\n--------------------------------")
    print("RAG retrieval + Groq ready.")
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
            results = search(question, model, chunks, embeddings)
            answer = generate_answer(question, results)

        print("\nAnswer:")
        print(answer)