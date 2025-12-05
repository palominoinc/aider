# Debug Session Summary: Verbose Payload Output & MCP Tools Issue

## Date
2025-12-04

## Initial Request
Add verbose debug output to show the exact payload being sent to the LLM when `--verbose` flag is set in aider.

## Issues Discovered & Resolved

### Issue 1: Verbose Output Missing Messages
**Problem:** The initial `dump(kwargs)` in `models.py:1003-1004` was called BEFORE messages were added to kwargs (line 1005), so the verbose output was incomplete.

**Solution:** Moved verbose output to line 1015-1016, right before `litellm.completion(**kwargs)` call, ensuring all components are included:
- Messages
- Tools
- Tool choice
- Timeout
- Extra headers (GitHub Copilot if configured)

### Issue 2: Verbose Output Not Detailed Enough
**Problem:** Using `dump(kwargs)` with json.dumps had issues serializing complex objects and was hard to read.

**Solution:** Created structured verbose output in `models.py:1016-1052` showing:
- Model, stream, temperature, timeout
- Tools list with names and count
- Tool choice setting
- Messages count with previews (first 100 chars of each)
- Extra params
- Raw kwargs dict (with message count instead of full content)

### Issue 3: Unclear Which Code Path Was Executing
**Problem:** Multiple verbose output locations made it hard to identify which one was printing.

**Solution:** Added unique labeled markers:
- `▶▶▶ [models.py:998] BEFORE adding messages/timeout ▶▶▶`
- `▶▶▶ [models.py:1017] FINAL PAYLOAD - Right before litellm.completion() ▶▶▶`
- `▶▶▶ [models.py:1068] simple_send_with_retries - messages only ▶▶▶`

### Issue 4: Tools Not Being Sent to API (ROOT CAUSE)
**Problem:** Despite having 20 MCP functions available, they weren't being added to the API payload.

**Diagnosis:**
```
[DEBUG] functions is None: False
[DEBUG] functions count: 20
[DEBUG] supports_function_calling: False  ← THE PROBLEM
[DEBUG] Skipping tools - either functions is None or model doesn't support function calling
```

The model `openai/gpt-5-chat-latest` had `supports_function_calling: false` in its metadata.

**Solution:** Created `.aider.model.metadata.json` with correct metadata:
```json
{
  "openai/gpt-5-chat-latest": {
    "max_tokens": 16384,
    "max_input_tokens": 128000,
    "max_output_tokens": 16384,
    "input_cost_per_token": 0.000001,
    "output_cost_per_token": 0.000003,
    "litellm_provider": "openai",
    "mode": "chat",
    "supports_function_calling": true,
    "supports_tool_choice": true,
    "supports_vision": true
  }
}
```

**Note:** This file AUGMENTS (not replaces) `aider/resources/model-metadata.json`. User files override built-in settings for matching model names.

### Issue 5: LLM Returns Empty Chunks
**Problem:** After fixing the metadata:
- ✅ Tools are being sent (all 20 tools visible in payload)
- ✅ API responds with 200 status
- ✅ 12 chunks received
- ❌ BUT: All chunks are empty - no content, no tool_calls, no function_call
- ❌ Result: "Empty response received from LLM"

**Current Status:** Added detailed chunk inspection in `base_coder.py:1948-1979` to show:
- Actual VALUES of content, tool_calls, function_call (not just attribute existence)
- Finish reason if present
- All delta attributes
- First 5 chunks with full details

**Pending:** Waiting for test results to see what's actually in the chunks.

## Files Modified

### aider/models.py
1. **Line 998-1000:** Added debug output BEFORE messages/timeout added
2. **Line 1015-1055:** Added comprehensive verbose payload output
3. **Line 1075-1100:** Added response debugging (type, choices, headers, exceptions)
4. **Line 970-1005:** Added function calling debug output showing:
   - Whether functions is None
   - Function count
   - supports_function_calling value
   - is_ask_mode detection
   - Confirmation when tools are added

### aider/coders/base_coder.py
1. **Line 1944-1979:** Added detailed chunk inspection in `show_send_output_stream`:
   - Chunk type and structure
   - Choice and delta attributes
   - Actual VALUES of content/tool_calls/function_call
   - Finish reason
2. **Line 2035-2045:** Added stream completion summary showing:
   - Total chunks received
   - Whether any content was received
   - Response content length
   - Function call data

### .aider.model.metadata.json (NEW FILE)
Created model metadata override to enable function calling for `openai/gpt-5-chat-latest`.

## Debug Output Flow

When running with `--verbose`, you now see:

1. **Function Detection** (`models.py:970-974`)
   ```
   [DEBUG] functions is None: False
   [DEBUG] functions count: 20
   [DEBUG] supports_function_calling: True
   ```

2. **Pre-Send Payload** (`models.py:998`)
   ```
   ▶▶▶ [models.py:998] BEFORE adding messages/timeout ▶▶▶
   kwargs: {model, stream, tools, tool_choice}
   ```

3. **Final Payload** (`models.py:1017`)
   ```
   ▶▶▶ [models.py:1017] FINAL PAYLOAD - Right before litellm.completion() ▶▶▶
   === Full API Payload ===
   Model: ...
   Tools (20 total): [list of tool names]
   Messages (6 total): [previews]
   Raw kwargs dict: [complete structure]
   ```

4. **Response Received** (`models.py:1075`)
   ```
   ▶▶▶ [models.py] Response received ▶▶▶
   Response type, headers, hidden params
   ```

5. **Chunk Processing** (`base_coder.py:1948-1979`)
   ```
   [DEBUG] Chunk #1:
     Delta.content VALUE: None
     Delta.tool_calls VALUE: None
     Finish reason: None
   ```

6. **Stream Summary** (`base_coder.py:2035-2045`)
   ```
   [DEBUG] Finished processing stream
     Total chunks: 12
     Received content: False
   ```

## Key Learnings

1. **Model Metadata Override:** User-created `.aider.model.metadata.json` files augment (not replace) built-in metadata
2. **Function Calling Check:** The `supports_function_calling` flag is checked BEFORE adding tools to kwargs
3. **Ask Mode Detection:** All functions starting with "mcp_" triggers ask mode (tool_choice: "auto")
4. **Chunk Structure:** Even "empty" responses return chunks - they just contain None/empty values

## Next Steps

1. Test with the enhanced chunk debugging to see actual values
2. Possible issues to investigate:
   - Model doesn't actually support function calling
   - Model returns data in unexpected format
   - Model silently rejects the request
   - LiteLLM parsing issue
3. Consider testing with known working model (gpt-4o) to verify MCP tools work
4. May need to check OpenAI API compatibility for gpt-5-chat-latest

## Command for Testing

```bash
./venv/bin/pip install . && ~/systems/aider-dev/venv/bin/aider \
  --enable-mcp \
  --verbose \
  --edit-format ask \
  --message 'how many webpal files are there. use the count files tool' \
  > /tmp/aider.log 2>&1
```

Check `/tmp/aider.log` for detailed debug output.
