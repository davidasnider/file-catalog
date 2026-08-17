import re
import asyncio

# Mock the variables
file_path = "dummy.cdx"
logger = type("Logger", (object,), {"info": lambda self, x: print(x)})()


# The proposed fix from the finding:
async def extract_cdx():
    def _read_cdx():
        with open(file_path, "rb") as f:
            content = f.read()
        # Extract printable strings as a fallback for binary CDX files (ASCII range)
        strings = re.findall(b"[\x20-\x7e]{4,}", content)
        return "\n".join([s.decode("ascii", errors="ignore") for s in strings])

    extracted_text = await asyncio.to_thread(_read_cdx)
    return extracted_text


# The proposed fix from the finding:
async def extract_wp():
    def _read_wp():
        with open(file_path, "rb") as f:
            content = f.read()
        # Extract printable sequences of 4+ characters
        strings = re.findall(b"[\x20-\x7e]{4,}", content)
        extracted_text = "\n".join(
            [s.decode("ascii", errors="ignore") for s in strings]
        )
        return extracted_text, len(strings)

    extracted_text, num_strings = await asyncio.to_thread(_read_wp)
    print(f"Extracted {num_strings} strings from WordPerfect file")
    return extracted_text


print("Code is valid.")
