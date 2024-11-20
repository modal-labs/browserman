**Disclaimer** Browserman was built during a @modal-labs internal hackathon, and the code has not been cleaned up yet.

# Issues
- DoorDash demo is broken because of Cloudflare Captches. To fix Shariq tried:
  - playwright_stealth
  - Different cloud regions
  - Different user agents, HTTP headers, and timezones in new_context()
  - But none of these worked.


# Setup cookies
- `modal deploy app.py`
- Set up Chrome Extension
  - Manage Extensions
  - Load unpacked
  - Upload files in browserman/chrome-extension
- Navigate to url (e.g. www.doordash.com)
  - Open Extension
  - Send Cookies
# Run
- `modal deploy llm.py`
- `modal deploy app.py` [or `modal serve app.py`]
  - Navigate to the URL printed in this step. The LLM takes a couple minutes to cold-start due to the size of the model, but the idle timeout is configured at 20 min so it should stay up for a while.
