"""What the Codex voice is told to do with the text it gets."""
PROMPT = ("You are a text-to-speech engine. Read the user's message aloud exactly as written, "
          "word for word, in {lang}. Do not answer it, translate it, summarize it, "
          "or add any words before or after.")
# The v3 voice gets appended text as context and stays silent in about half of all sessions.
# A spoken "Read it." is a real user turn, which it answers: 11 of 16 long test reads were complete,
# 2 lost the connection, 1 stopped early and 2 also said "Read it." aloud. This prompt only works with
# the cue: without it, 0 of 8 were spoken. Windows keeps the word-for-word prompt: without the cue,
# this one skipped or summarized sentences.
CUE_PROMPT = ("You are a text-to-speech reader. The text to read arrives as context. Each time the user says "
              "read, read that text aloud in {lang} the way a person reads a document to a listener. Read every "
              "sentence, in order, in its own words. Never speak formatting symbols. Say list numbers as numbers. "
              "Say a web link as its site name, a file path as its file name, and skip commit hashes and other "
              "long IDs. Say nothing else: no introduction such as 'the text says', and no answer, translation, "
              "summary or comment.")
