import os
import unittest

from crew.crew import KYCCrew


class TestModelResolution(unittest.TestCase):
    def test_llm_refreshes_when_model_env_changes(self):
        original_model = os.environ.get("MODEL")
        try:
            os.environ.pop("MODEL", None)
            crew = KYCCrew()
            llm1 = crew.llm

            os.environ["MODEL"] = "bedrock/us.amazon.nova-pro-v1:0"
            llm2 = crew.llm

            self.assertIsNot(llm1, llm2)
        finally:
            if original_model is None:
                os.environ.pop("MODEL", None)
            else:
                os.environ["MODEL"] = original_model


if __name__ == "__main__":
    unittest.main()
