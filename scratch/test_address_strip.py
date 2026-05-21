
import sys
import os
sys.path.append(os.getcwd())
from synonym_loader import get_address_tokens

tokens = get_address_tokens("MX")
print(f"Address tokens for MX: {sorted(list(tokens))}")

from es_queries import _strip_address_python
name = "HOG SLAT INTERNATIONAL, S. DE R.L. DE C.V."
cleaned = _strip_address_python(name, "MX")
print(f"Original: {name}")
print(f"Cleaned:  {cleaned}")
