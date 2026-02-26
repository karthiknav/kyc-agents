import os
import logging

# Show tool debug (what gets passed to SearchTool)
logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")

from crew import ResearchCrew

# Create output directory if it doesn't exist
os.makedirs('output', exist_ok=True)

def run():
    """
    Run the research crew.
    """
    inputs = {
        'topic': 'Artificial Intelligence in Healthcare'
    }

    # Create and run the crew
    result = ResearchCrew().crew().kickoff(inputs=inputs)

    # Print the result
    print("\n\n=== FINAL REPORT ===\n\n")
    print(result.raw)


if __name__ == "__main__":
    run()