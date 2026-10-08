# Domain vocabulary

- **Library**: the single local collection of uploaded and indexed documents.
- **Training**: extracting text, splitting it into chunks, creating embeddings,
  and indexing them so chat can search them. It does not change model weights.
- **Cancel training**: stop an unfinished training operation, retaining the file.
- **Remove indexing**: exclude a trained document from search, retaining the file.
- **Delete file**: remove the file and all its indexed chunks from the library.
- **Conversation**: a saved sequence of questions, answers and source references.
- **Source**: an original document excerpt or visual supporting a particular answer.
- **PDF extraction provider**: the selected service or model that reads a PDF
  into text before the document is trained for library search.
- **Local OCR**: reading document images into text with a model running on the
  same computer as the library application.

## Visual sources

**Document image**:
An original visual contained in a library document, such as a figure, chart,
or illustration.
_Avoid_: Image description

**Image description**:
A generated textual description of a document image used to help find it.
It may be incomplete or inaccurate and is distinct from the original visual.
_Avoid_: Original image, verified visual evidence
