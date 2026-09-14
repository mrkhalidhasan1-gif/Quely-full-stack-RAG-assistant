import sys
import json
import numpy as np
from sentence_transformers import SentenceTransformer


# --------------------------------
# Arguments
# --------------------------------

if len(sys.argv) < 3:
    print("QUELY_ERROR: Missing document path or question")
    sys.exit(1)

document_path = sys.argv[1]
question = sys.argv[2]


# --------------------------------
# Prepare arguments for rag.py
# --------------------------------

sys.argv = ["rag.py", document_path]


# --------------------------------
# Import RAG functions
# --------------------------------

from rag import load_vectors, search, generate_answer


# --------------------------------
# Load saved vectors
# --------------------------------

saved = load_vectors()

if not saved:
    print("QUELY_ERROR: No saved vectors found")
    sys.exit(1)

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


# --------------------------------
# Load embedding model
# --------------------------------

model = SentenceTransformer("BAAI/bge-small-en-v1.5")


# --------------------------------
# Semantic retrieval
# --------------------------------

results = search(question, model, chunks, embeddings)


# --------------------------------
# Generate grounded answer
# --------------------------------

answer = generate_answer(question, results)


# --------------------------------
# Return result to Node
# --------------------------------

sources = [
    {
        "page": result["page"],
        "section": result["section"],
        "score": result["score"]
    }
    for result in results
]

print("QUELY_RESULT:" + json.dumps({
    "answer": answer,
    "sources": sources
}))