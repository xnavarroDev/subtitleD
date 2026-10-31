# Combining, translating, and splitting passages

Use the checkboxes beside adjacent caption numbers and choose **Combine selected**.
Save/discard existing drafts first. This joins the source and translated text
into one caption and retains the original caption parts and timings in the
project database. Raw WhisperX word records are never changed.

Choose **Retranslate passage** to translate that entire source passage. HY-MT2
also receives the configured number of previous/next source captions as context;
the default is two. NLLB translates the combined passage but does not interpret
separate conversation context. Results enter an unsaved draft, with the actual
provider and any fallback warning shown. Save the wording before splitting.

Choose **Split to original captions** to restore the recorded source text and
timings. If the translation has not changed, the original translations are
restored too. If it has changed, the full new translation starts in the first
part. Place the cursor at a sentence/clause boundary and choose **Move text after
cursor to next caption**, repeating as necessary. Edit each part, then choose
**Save split captions**. Every part needs translation text; no model guesses the
timing of reordered translated words. Cancel keeps the combined caption.

For an ordinary caption, **Split caption** creates two editable parts at the
playhead, or the midpoint if the playhead is outside the caption. The source text
is initially divided near its middle (including Mandarin without spaces).
Review both text parts. The server requires the complete original transcript
and time range to be preserved. New timing is marked estimated for review.

Combining and splitting invalidate generated subtitle/video exports. Exports
must be regenerated after edits. Concurrent/stale structure edits are rejected,
and structure edits are blocked during processing. Re-transcribing or
translating the entire project again replaces caption structure as stated in
the processing toolbar; use passage retranslation to preserve manual grouping.

## One backup translator

The supported default chain is HY-MT2 → NLLB 600M (CTranslate2, CPU INT8).
NLLB can also be selected directly. It must first be explicitly installed through
the companion, or `python local_connector.py prepare-translation`. This checks
for active jobs, installs/repairs the selected model, and runs an actual short
translation before reporting success. No extra backup models are downloaded.
Legacy LibreTranslate API configuration is retained for existing projects, but
it is no longer offered as a default choice or called as a fallback.

The [NLLB model card](https://huggingface.co/facebook/nllb-200-distilled-600M)
documents its non-commercial license and intended use. NLLB passages that exceed
its configured token limit are rejected with instructions to split the passage;
they are not silently truncated.
