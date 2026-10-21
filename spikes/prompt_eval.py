"""PROTOTYPE (throwaway): do the Writer, Summarize, and read-aloud prompts do their job on real models?

Usage:
  uv run python spikes/prompt_eval.py writer [--sources Codex,Local,Cursor] [--label new] [--runs 3]
  uv run python spikes/prompt_eval.py summarize [--label new] [--runs 3]
  uv run python spikes/prompt_eval.py read [--label new] [--cue]      # --cue: the Mac cue path, long fixtures x8
  uv run python spikes/prompt_eval.py report base new                 # -> spikes/out/prompt_eval.md
Runs against whatever `harness_discussion` is importable, so the same file measures the base commit too.
A case passes a hard check only when every run passes. Results go to spikes/out/prompt_eval_<label>.json.
"""
import argparse, inspect, json, re, sys, threading, time
from pathlib import Path

from harness_discussion import lang, summarize, writer

HERE = Path(__file__).parent
OUT = HERE / "out"
FIX = HERE / "fixtures"
PREAMBLE = re.compile(r"(here('s| is| are)|sure|certainly|of course|rewritten|revised|below)\b.*:\s*$", re.I)
BANNED_CHARS = "—“”‘’…"
BANNED_WORDS = ["delve", "robust", "seamless", "leverage", "utilize", "pivotal", "crucial", "foster", "underscore",
                "showcase", "streamline", "all-encompassing", "it's worth noting", "fast-paced"]
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
SCRIPTS = {"he": (0x0590, 0x05FF), "ru": (0x0400, 0x04FF)}


def tidy(out, original):
    return writer.tidy(out, original) if hasattr(writer, "tidy") else out.strip()


def has_script(text, lo, hi):
    return any(lo <= ord(c) <= hi for c in text)


def lang_kept(src, out, mixed):
    if mixed:
        return has_script(out, *SCRIPTS["he"]) and bool(re.search(r"[A-Za-z]", out))
    return lang.detect(out) == lang.detect(src)  # Latin-script languages are caught by must_contain words


def preamble(raw, src):
    first, _, rest = raw.strip().partition("\n")
    return bool(rest.strip()) and bool(PREAMBLE.match(first.strip())) and not src.strip().startswith(first.strip())


def sentences_of(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def norm_ws(s):
    return " ".join(s.split())


class Recorder:
    """Passes every attribute through, and keeps the raw reply before writer.rewrite tidies it."""
    def __init__(self, source):
        self._source, self.raw = source, None

    def __getattr__(self, name):
        return getattr(self._source, name)

    def rewrite(self, *args):
        self.raw = self._source.rewrite(*args)
        return self.raw


def make_sources(names):
    from harness_discussion.llm_codex import CodexWriter
    from harness_discussion.llm_cursor import CursorWriter
    server = summarize.Server()
    made = {"Codex": CodexWriter, "Cursor": CursorWriter, "Local": lambda: summarize.LocalWriter(server)}
    return {n: made[n]() for n in names}, server


def check_writer(case, raw, out):
    src = case["text"]
    stripped = CODE.sub("", out)
    hard = {
        "non_empty": bool(out.strip()),
        "no_preamble_raw": not preamble(raw or "", src),
        "no_preamble": not preamble(out, src),
        "no_tag_echo": "<text>" not in out and "</text>" not in out,
        "language": lang_kept(src, out, case.get("mixed")),
        "contains": all(s in out for s in case.get("must_contain", [])),
        "not_contains": not any(s.lower() in out.lower() for s in case.get("must_not_contain", [])),
        "max_lines": len(out.strip().splitlines()) <= case.get("max_lines", 10 ** 6),
    }
    if case.get("unchanged"):
        hard["unchanged"] = norm_ws(out) == norm_ws(tidy(src, src))
    soft = {"plain_chars": not any(c in stripped for c in BANNED_CHARS),
            "no_banned_words": not any(w in stripped.lower() for w in BANNED_WORDS)}
    if case["mode"] != "Fix errors":
        lengths = [len(s.split()) for s in sentences_of(stripped)] or [0]
        soft["short_sentences"] = sum(lengths) / len(lengths) <= 20
    return hard, soft


def run_writer(args):
    cases = json.loads((FIX / "writer.json").read_text(encoding="utf-8"))
    sources, server = make_sources(args.sources.split(","))
    has_language = "language" in inspect.signature(writer.rewrite).parameters
    modes = writer.all_modes([])
    results = []
    try:
        for name, source in sources.items():
            if source.status() != "ready":
                print(f"skip {name}: {source.status()}")
                continue
            for case in cases:
                mode = writer.find_mode(case["mode"], modes)
                for n in range(args.runs):
                    rec = Recorder(source)
                    kw = {"language": lang.name(lang.detect(case["text"])) or "the language of the text"} \
                        if has_language else {}
                    t0 = time.monotonic()
                    try:
                        # default effort can run past the writer's 60 s timeout on some texts, base or new prompt
                        models = {"Codex": {"effort": args.effort}} if args.effort else None
                        out, _ = writer.rewrite(case["text"], mode, [rec], models=models, **kw)
                        error = None
                    except Exception as e:
                        out, error = "", type(e).__name__
                    hard, soft = check_writer(case, rec.raw, out)
                    if error:
                        hard["no_error"] = False
                    results.append({"source": name, "id": case["id"], "mode": case["mode"], "run": n, "raw": rec.raw,
                                    "out": out, "error": error, "hard": hard, "soft": soft,
                                    "s": round(time.monotonic() - t0, 1)})
                    bad = [k for k, v in hard.items() if not v]
                    print(f"{name:6} {case['id']:12} #{n} {'PASS' if not bad else 'FAIL ' + ','.join(bad)}", flush=True)
    finally:
        server.stop()
    return results


def run_summarize(args):
    cases = json.loads((FIX / "summarize.json").read_text(encoding="utf-8"))
    server = summarize.Server()
    results = []
    try:
        for case in cases:
            for n in range(args.runs):
                try:
                    out, error = server.summarize(case["text"], case["lang"]), None
                except Exception as e:
                    out, error = "", type(e).__name__
                count = len(sentences_of(out))
                hard = {"non_empty": bool(out), "sentences": 1 <= count <= 5,
                        "language": lang_kept(case["text"], out, case.get("mixed")),
                        "not_answered": case["id"] != "injection" or not re.search(r"\b(4|four)\b", out, re.I)}
                # every voice reads $ and % itself, a spelled-out link is the real miss
                soft = {"spoken": not re.search(r"https?://|\bslash\b|[#*`]", out, re.I),
                        "no_intro": not re.match(r"(the|this) (text|article|passage) (says|is about|describes)", out,
                                                 re.I)}
                results.append({"id": case["id"], "run": n, "out": out, "error": error, "hard": hard, "soft": soft})
                bad = [k for k, v in hard.items() if not v]
                print(f"{case['id']:12} #{n} {'PASS' if not bad else 'FAIL ' + ','.join(bad)}", flush=True)
    finally:
        server.stop()
    return results


def wer(ref, hyp):
    norm = lambda s: re.sub(r"[^\w\s]", " ", s.lower()).split()
    r, h = norm(ref), norm(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
    return d[len(h)] / max(len(r), 1)


def read_once(engine, text, tag):
    """The voice's whole transcript. Captions restart at each piece, so the last caption of each piece is kept."""
    from harness_discussion import richtext
    pieces, last, done, err = [], [""], threading.Event(), []

    def on_caption(c):
        if last[0] and not c.startswith(last[0]):
            pieces.append(last[0])
        last[0] = c

    engine.speak(text, tag, lambda e: (err.append(e), done.set()), on_caption=on_caption)
    done.wait(600)
    heard = " ".join(pieces + [last[0]])
    ref = richtext.speakable(richtext.strip_markup(text)).strip() or text
    return ref, heard, (err[0] if err else "timeout")


def run_read(args):
    from harness_discussion import codex_rt
    if args.cue:
        plan = [("long_en", "en-US"), ("long_he", "he-IL")] * 8
        bar = 0.10
    else:
        plan = [(f, t) for f in ("en", "he", "mixed", "numbers") for t in [lang.detect((FIX / f"{f}.txt").read_text(
            encoding="utf-8"))]] * 3
        bar = 0.05
    engine = codex_rt.CodexEngine()
    results = []
    try:
        for name, tag in plan:
            text = (FIX / f"{name}.txt").read_text(encoding="utf-8").strip()
            ref, heard, error = read_once(engine, text, tag)
            score = wer(ref, heard)
            ok = error is None and score <= bar
            results.append({"id": name, "wer": round(score, 3), "error": repr(error) if error else None, "heard": heard,
                            "hard": {"complete": ok}, "soft": {}})
            print(f"{name:8} wer={score:.3f} {'PASS' if ok else 'FAIL'} {error or ''}", flush=True)
    finally:
        engine.close()
    return results


def rates(results, key):
    by = {}
    for r in results:
        for k, v in r[key].items():
            by.setdefault(k, []).append(v)
    return {k: f"{sum(v)}/{len(v)}" for k, v in by.items()}


def report(base_label, new_label):
    lines = ["# Prompt eval: base vs new", ""]
    for kind in ("writer", "summarize", "read"):
        files = {lbl: OUT / f"prompt_eval_{kind}_{lbl}.json" for lbl in (base_label, new_label)}
        if not all(f.exists() for f in files.values()):
            continue
        data = {lbl: json.loads(f.read_text(encoding="utf-8")) for lbl, f in files.items()}
        lines += [f"## {kind}", "", "| label | source | hard | soft |", "| --- | --- | --- | --- |"]
        for lbl, rs in data.items():
            for src in sorted({r.get("source", "-") for r in rs}):
                sub = [r for r in rs if r.get("source", "-") == src]
                lines.append(f"| {lbl} | {src} | {rates(sub, 'hard')} | {rates(sub, 'soft')} |")
        lines.append("")
        if kind == "read":
            continue
        cases = json.loads((FIX / f"{kind}.json").read_text(encoding="utf-8"))
        for case in cases:
            lines += [f"### {case['id']}" + (f" ({case['mode']})" if "mode" in case else ""), "",
                      "Input:", "", "```text", case["text"], "```", ""]
            for lbl, rs in data.items():
                for r in [r for r in rs if r["id"] == case["id"] and r["run"] == 0]:
                    bad = [k for k, v in r["hard"].items() if not v]
                    lines += [f"**{lbl} · {r.get('source', 'Local')}**" + (f" · FAIL {bad}" if bad else ""), "",
                              "```text", r["out"] or f"(error {r['error']})", "```", ""]
    (OUT / "prompt_eval.md").write_text("\n".join(lines), encoding="utf-8")
    print(OUT / "prompt_eval.md")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["writer", "summarize", "read", "report"])
    ap.add_argument("labels", nargs="*")
    ap.add_argument("--sources", default="Codex,Local")
    ap.add_argument("--label", default="new")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--cue", action="store_true")
    ap.add_argument("--effort", default="low", help="Codex reasoning effort; empty for the app default")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    if args.kind == "report":
        return report(*args.labels)
    results = {"writer": run_writer, "summarize": run_summarize, "read": run_read}[args.kind](args)
    suffix = "_cue" if args.cue else ""
    (OUT / f"prompt_eval_{args.kind}{suffix}_{args.label}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    for src in sorted({r.get("source", "-") for r in results}):
        sub = [r for r in results if r.get("source", "-") == src]
        print(src, "hard", rates(sub, "hard"), "soft", rates(sub, "soft"))


if __name__ == "__main__":
    sys.exit(main())
