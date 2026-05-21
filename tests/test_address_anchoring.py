
import unittest
import sys
import os

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from es_queries import _strip_address_python
from synonym_loader import get_address_tokens, get_legal_suffix_patterns

class TestAddressAnchoring(unittest.TestCase):

    def test_suffix_anchoring_mx(self):
        # Case 1: S. de R.L. prefix "S." should NOT be stripped
        name1 = "HOG SLAT INTERNATIONAL, S. DE R.L. DE C.V."
        # Before fix, this would return "HOG SLAT INTERNATIONAL," because of the 'S'
        result1 = _strip_address_python(name1, "MX")
        self.assertEqual(result1, name1, "Should not strip anything when no address follows suffix")

        # Case 2: Address AFTER suffix SHOULD be stripped
        name2 = "HOG SLAT INTERNATIONAL, S. DE R.L. DE C.V. CALLE 2"
        # Only ' CALLE 2' should be targeted
        result2 = _strip_address_python(name2, "MX")
        self.assertEqual(result2, "HOG SLAT INTERNATIONAL, S. DE R.L. DE C.V.", "Should strip address only after suffix")

        # Case 3: No suffix = No strip (Safe Fallback)
        name3 = "NORTH FACE INTL"
        # 'NORTH' previously conflict with North abbreviation. Without a suffix, we don't strip.
        result3 = _strip_address_python(name3, "MX")
        self.assertEqual(result3, name3, "Should not strip anything if no legal suffix is found")

    def test_suffix_anchoring_us(self):
        # Case 4: US Suffix
        name4 = "ACME CORP STREET 123"
        # 'CORP' is suffix. ' STREET 123' is address.
        result4 = _strip_address_python(name4, "US")
        self.assertEqual(result4, "ACME CORP", "Should strip address after US suffix")

    def test_key_mismatch_correction(self):
        # Verify MX tokens are loaded from address_terms
        tokens = get_address_tokens("MX")
        self.assertIn("calle", tokens)
        self.assertIn("avenida", tokens)
        # Verify 's' is still there from common.json
        self.assertIn("s", tokens)

if __name__ == "__main__":
    unittest.main()
