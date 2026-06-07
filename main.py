import os
import json
from dotenv import load_dotenv

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate

from structured import Reference


load_dotenv()

# check if the api key exists
if not os.getenv("GOOGLE_API_KEY"):
    raise EnvironmentError("GOOGLE_API_KEY is missing from .env file")


# model to be used
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0
)

# returns the output in the specified pydantic format
structured_llm = llm.with_structured_output(Reference)

prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
You are a reference metadata extraction assistant.

Your task is to extract structured metadata from ONE raw academic or web reference.

Return the result using the provided structured schema.

Rules:
1. The input will contain only one reference.
2. Do not verify whether the reference is real.
3. Do not correct the reference.
4. Do not invent missing information.
5. Keep raw_reference exactly as provided.
6. If a field is missing or unclear, return null or an empty list.
7. Extract DOI only if clearly present.
8. Extract URL only if clearly present.
9. Authors must be returned as a list.
10. Source may be a journal, conference, book, website, publisher, or organisation.
"""
    ),
    (
        "human",
        """
Extract metadata from this reference:

{reference}
"""
    )
])

# chain is invoked with reference to get the metadata of the reference
chain = prompt | structured_llm




def metadata(reference):
    result = chain.invoke({"reference": reference})
    # ensure ascii will ensure that the unicode characters will also be printed instead of being escaped
    return(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))

reference = """
Smith, J. (n.d.). Notes on machine ethics. Retrieved from example.org.
"""

print(metadata(reference))