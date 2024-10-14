**Disclaimer** Browserman was built during a @modal-labs internal hackathon, and the code has not been cleaned up yet.

# Run
- `modal deploy llm.py`
- `modal deploy app.py` [or `modal serve app.py`]
  - Navigate to the URL printed in this step. The LLM takes a couple minutes to cold-start due to the size of the model, but the idle timeout is configured at 20 min so it should stay up for a while.
