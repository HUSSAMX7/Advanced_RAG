# Independent stores for assistants

Each assistant owns separate document, image, FAISS and conversation directories,
while credentials and model choices remain application-wide. FAISS retrieval does
not support metadata filtering, so independent stores make the ownership boundary
apply equally to search and direct file/source access; this costs additional index
directories compared with a shared index. Local training and retrieval retain a
shared operation lock to avoid concurrent OCR/model work on the same machine.
