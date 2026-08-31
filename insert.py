from llama_parse import LlamaParse
from dotenv import load_dotenv
import os
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LLAMA_PARSE_API_KEY = os.getenv("LLAMA_PARSE_API_KEY")

parser = LlamaParse(api_key=LLAMA_PARSE_API_KEY,result_type="markdown")

file_name  = r"C:\Users\hosam\OneDrive\سطح المكتب\test.pdf"

extra_info = {"file_name":file_name}


with open(file_name, "rb") as f:
   # must provide extra_info with file_name key with passing file object
   documents = parser.load_data(f, extra_info=extra_info)


with open("output.md", "w", encoding="utf-8") as f:
   for doc in documents:
       f.write(doc.text)