from llama_parse import LlamaParse
from dotenv import load_dotenv
import os

load_dotenv()

LLAMA_PARSE_API_KEY = os.getenv("LLAMA_PARSE_API_KEY")

parser = LlamaParse(
    api_key=LLAMA_PARSE_API_KEY,
    result_type="markdown"
)

file_name = r"C:\Users\hosam\OneDrive\سطح المكتب\الذكاء الاصطناعي في بيئة العمل ملخص.pdf"

extra_info = {
    "file_name": file_name
}

with open(file_name, "rb") as f:
    documents = parser.load_data(
        f,
        extra_info=extra_info
    )

text = documents.text



with open("output.md", "w", encoding="utf-8") as f:
    for doc in documents:
        f.write(doc.text)

