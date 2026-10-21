# Session memory

Agreed in the chat on 2026-10-11.

- Send every saved question and answer from the same session in chronological order,
  retaining their user/assistant roles and saved source references. Add the current
  question once. Replay this context in both the search request and final answer request.
- Identify earlier messages and any conversation summary as past conversation context.
  Document answers must still rely on newly retrieved original excerpts and visuals;
  previous answers and summaries are not document evidence.
- Send full history until the provider reports a context capacity error. Disable automatic
  provider truncation so older messages cannot disappear silently.
- On overflow, summarize older turns using the configured chat model, retaining the latest
  ten complete exchanges. Process older messages in bounded fragments, reducing fragment
  sizes if the summarizer itself exceeds capacity.
- Save the summary and the count of covered turns only with a successful, validated answer.
  Reuse that summary with all uncovered messages. When capacity is exceeded again, extend
  the summary with newly old turns and retry once. Preserve the current question, tool
  results and images without repeating document search.
- Keep every original saved turn; summaries never replace the stored or displayed messages.
  Summaries can lose detail, so keep preferences, decisions, identifiers, dates, numbers,
  corrections and unresolved questions explicit in the summarization instructions.
- If the remaining ten exchanges, question or evidence still exceed capacity, show an
  actionable error. Other API failures must not trigger summarization. Any failed request
  leaves the saved session and its memory unchanged.
- Resume older session files without requiring a summary field. Reject malformed saved memory.

