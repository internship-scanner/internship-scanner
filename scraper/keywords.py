"""Keyword extraction for internship postings.

Two passes:

1. CURATED — match against a hand-picked tech vocabulary (programming
   languages, frameworks, specializations, methodologies). This catches the
   high-value buzzwords that hiring managers actually filter on.

2. CORPUS-WEIGHTED — for each posting, score remaining unigrams/bigrams in
   the description by their inverse document frequency across the WHOLE
   scrape. Surface the top-N rare-and-relevant terms.

The output is a deduplicated list of keywords, ranked: curated matches
first (alphabetically), then high-IDF terms.

Pure TF-IDF on ~500 short descriptions would be noisy — too few documents
for stable inverse-document weights. The curated vocabulary acts as a
high-precision filter; the corpus weighting is a recall booster for niche
terms (e.g. "CUDA", "Triton", "JAX") that we didn't enumerate but appear
in only a few postings.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Iterable


# ---------------------------------------------------------------------------
# Curated tech vocabulary
# ---------------------------------------------------------------------------
# Each entry is matched as a whole word/phrase. Case-insensitive.
# Canonical form (what we output) on the left; aliases on the right.

CURATED_KEYWORDS: dict[str, list[str]] = {
    # Languages
    "Python":       ["python"],
    "C++":          [r"c\+\+", "cpp"],
    "C":            [r"\bc\b(?!\+\+|\#)"],  # bare C, not C++ or C#
    "Rust":         ["rust"],
    "Go":           ["golang", r"\bgo\b"],
    "Java":         ["java"],
    "Kotlin":       ["kotlin"],
    "Scala":        ["scala"],
    "TypeScript":   ["typescript"],
    "JavaScript":   ["javascript"],
    "Swift":        ["swift"],
    "Ruby":         ["ruby"],
    "PHP":          ["php"],
    "OCaml":        ["ocaml"],
    "Haskell":      ["haskell"],
    "Erlang":       ["erlang"],
    "Elixir":       ["elixir"],
    "Clojure":      ["clojure"],
    "SQL":          ["sql"],
    "R":            [r"\br\b(?:\s+programming|\s+language|\s+stats)"],
    "Julia":        [r"julia"],
    "MATLAB":       ["matlab"],
    "Bash":         ["bash", "shell scripting"],
    "Lua":          ["lua"],
    "Perl":         ["perl"],
    "Assembly":     ["assembly", "assembler"],
    "CUDA":         ["cuda"],
    "Triton":       [r"\btriton\b"],
    "Verilog":      ["verilog", "systemverilog"],
    "VHDL":         ["vhdl"],

    # ML / DL frameworks
    "PyTorch":          ["pytorch", "torch"],
    "TensorFlow":       ["tensorflow", "tf2"],
    "JAX":              [r"\bjax\b"],
    "Hugging Face":     ["hugging face", "huggingface", "transformers library"],
    "scikit-learn":     ["scikit-learn", "sklearn"],
    "Keras":            ["keras"],
    "ONNX":             ["onnx"],
    "MLflow":           ["mlflow"],
    "Weights & Biases": ["weights & biases", "wandb", "weights and biases"],
    "Ray":              [r"\bray\s+(?:rllib|cluster|train|serve)\b", "ray.io"],

    # ML/AI specializations
    "LLM":                ["llm", "large language model"],
    "RAG":                [r"\brag\b", "retrieval[- ]augmented"],
    "Diffusion Models":   ["diffusion model", "stable diffusion"],
    "Reinforcement Learning": ["reinforcement learning", r"\brl\b(?!hf)"],
    "RLHF":               ["rlhf"],
    "Computer Vision":    ["computer vision", r"\bcv\b"],
    "NLP":                ["nlp", "natural language processing"],
    "Speech Recognition": ["speech recognition", "asr", "automatic speech recognition"],
    "Recommender Systems":["recommender system", "recommendation system", "recsys"],
    "Time Series":        ["time series", "time-series"],
    "Generative AI":      ["generative ai", "genai", "generative models"],
    "Multimodal":         ["multimodal"],
    "AI Alignment":       ["alignment", "ai safety", "ai alignment"],
    "Inference Optimization": ["inference optimization", "model quantization",
                                "quantization", "model distillation",
                                "knowledge distillation"],
    "Foundation Models":  ["foundation model"],
    "Embeddings":         ["embedding", "vector search", "semantic search"],

    # Data
    "Spark":     ["apache spark", r"\bspark\b"],
    "Kafka":     ["kafka"],
    "Airflow":   ["airflow"],
    "Snowflake": ["snowflake"],
    "BigQuery":  ["bigquery"],
    "Databricks":["databricks"],
    "dbt":       [r"\bdbt\b"],
    "Flink":     ["flink"],
    "Hadoop":    ["hadoop"],
    "Beam":      ["apache beam"],
    "ClickHouse":["clickhouse"],
    "DuckDB":    ["duckdb"],
    "Postgres":  ["postgres", "postgresql"],
    "MongoDB":   ["mongodb", "mongo db"],
    "Redis":     ["redis"],
    "Elasticsearch":["elasticsearch", "elastic search"],
    "Cassandra": ["cassandra"],
    "Parquet":   ["parquet"],
    "Iceberg":   ["apache iceberg", "iceberg tables"],

    # Cloud / infra
    "AWS":         [r"\baws\b", "amazon web services"],
    "GCP":         [r"\bgcp\b", "google cloud platform", "google cloud"],
    "Azure":       [r"\bazure\b"],
    "Kubernetes":  ["kubernetes", "k8s"],
    "Docker":      ["docker"],
    "Terraform":   ["terraform"],
    "Pulumi":      ["pulumi"],
    "Helm":        [r"\bhelm\b"],
    "Istio":       ["istio"],
    "Envoy":       ["envoy proxy", r"\benvoy\b"],
    "gRPC":        ["grpc"],
    "GraphQL":     ["graphql"],
    "REST APIs":   ["rest api", "restful"],
    "WebSockets":  ["websocket"],
    "Microservices":["microservice"],
    "Serverless":  ["serverless", "lambda functions"],
    "Service Mesh":["service mesh"],
    "OpenTelemetry":["opentelemetry", "otel"],

    # Frontend
    "React":       ["react", "react.js", "reactjs"],
    "Next.js":     ["next.js", "nextjs"],
    "Vue":         [r"\bvue\b", "vue.js"],
    "Svelte":      ["svelte", "sveltekit"],
    "Angular":     ["angular"],
    "WebGL":       ["webgl"],
    "WebAssembly": ["webassembly", "wasm"],
    "Tailwind":    ["tailwind", "tailwindcss"],

    # Mobile
    "iOS":         [r"\bios\b"],
    "Android":     ["android"],
    "React Native":["react native"],
    "Flutter":     ["flutter"],

    # Systems / low-level
    "Linux Kernel":      ["linux kernel", "kernel development"],
    "Embedded":          ["embedded systems", "embedded c"],
    "RTOS":              ["rtos", "real-time os", "real time operating system"],
    "FPGA":              ["fpga"],
    "ASIC":              ["asic design"],
    "Compilers":         ["compiler design", "compilers", "llvm"],
    "LLVM":              ["llvm"],
    "Distributed Systems":["distributed systems", "distributed system"],
    "Concurrency":       ["concurrency", "lock-free", "multi-threading"],
    "Low Latency":       ["low latency", "low-latency", "ultra low latency"],
    "High Performance":  ["high performance computing", r"\bhpc\b",
                          "high-performance"],
    "GPU Programming":   ["gpu programming", "gpu kernels"],

    # Security
    "Cryptography":     ["cryptography", "cryptographic"],
    "Reverse Engineering": ["reverse engineering"],
    "Penetration Testing": ["penetration testing", "pen testing", "pentest"],
    "Web Security":     ["web security", "owasp"],
    "Network Security": ["network security"],
    "Zero Trust":       ["zero trust", "zero-trust"],
    "PKI":              [r"\bpki\b", "public key infrastructure"],
    "TLS":              ["tls 1.3", r"\btls\b", "mutual tls", "mtls"],

    # Quant / fintech
    "Quantitative Research": ["quantitative research", "quant research"],
    "Algorithmic Trading":   ["algorithmic trading", "algo trading"],
    "Market Making":         ["market making", "market maker"],
    "Risk Modeling":         ["risk modeling", "risk modelling"],
    "Derivatives":           ["derivatives pricing", "options pricing"],
    "Blockchain":            ["blockchain", r"\bweb3\b", "ethereum", "solidity"],
    "Payments":              ["payment systems", "payment processing"],

    # Methods / general
    "CI/CD":           ["ci/cd", "continuous integration"],
    "TDD":             ["test-driven development", r"\btdd\b"],
    "Agile":           ["agile", "scrum"],
    "MLOps":           ["mlops"],
    "DevOps":          ["devops"],
    "Observability":   ["observability", "tracing", "distributed tracing"],
    "Site Reliability":["site reliability", r"\bsre\b"],
    "A/B Testing":     ["a/b test", "a/b testing", "ab testing", "split testing"],
    "Open Source":     ["open source contributor", "open source maintainer"],
    "Academic Research": ["published", "research paper", "phd candidate", "ph.d."],
}

# Compile alternation patterns once.
_CURATED_PATTERNS: list[tuple[str, "re.Pattern"]] = [
    (canonical, re.compile(r"(?:" + r"|".join(
        a if (r"\b" in a or r"\\" in a or a.startswith("\\")) else r"\b" + re.escape(a) + r"\b"
        for a in aliases
    ) + r")", re.IGNORECASE))
    for canonical, aliases in CURATED_KEYWORDS.items()
]


def curated_matches(text: str) -> list[str]:
    """Return alphabetically-sorted list of canonical keywords found in text."""
    if not text:
        return []
    hits = set()
    for canonical, pat in _CURATED_PATTERNS:
        if pat.search(text):
            hits.add(canonical)
    return sorted(hits)


# ---------------------------------------------------------------------------
# Corpus-weighted extraction
# ---------------------------------------------------------------------------

# Stopwords we never surface as keywords (common English + boilerplate from
# careers pages).
_STOPWORDS = set("""
a an and or the of in on for to from with by at as is are was were be been being
this that these those it its their they we you our your i me my mine
have has had do does did doing will would shall should could can may might must
not no nor only also any all some such other than then there here where when how why
about into through during before after above below up down out over again further
more most less least very much many few several any same own so just only really very
""".split())

# Things to NEVER surface even if they have low frequency.
_BANNED_TERMS = {
    # generic recruiting blurb
    "candidate", "candidates", "applicant", "applicants", "team", "teams",
    "company", "companies", "role", "roles", "position", "positions",
    "opportunity", "opportunities", "responsibility", "responsibilities",
    "requirement", "requirements", "qualification", "qualifications",
    "experience", "experienced", "skills", "skill", "ability", "abilities",
    "knowledge", "understanding", "background", "passionate", "passion",
    "looking", "join", "joining", "work", "working", "workplace", "workforce",
    "build", "building", "develop", "developing", "develops", "developed",
    "design", "designing", "support", "supporting", "supports",
    "internship", "intern", "interns", "student", "students", "praktikum",
    "year", "years", "month", "months", "week", "weeks",
    "office", "offices", "remote", "hybrid", "onsite",
    "english", "german", "french", "spanish", "italian",
    "monday", "tuesday", "wednesday", "thursday", "friday",
    "morning", "afternoon", "evening",
    "good", "great", "strong", "excellent", "best", "better",
    "new", "old", "young",
    "lot", "lots", "kind", "kinds", "type", "types", "way", "ways",
    "etc", "etc.", "e.g", "i.e",
    # nationality / location words handled elsewhere
    "european", "europe", "global", "international",
    # too generic
    "software", "engineer", "engineering", "developer", "development",
    "computer", "technology", "technical", "tech", "technologies",
    "data", "scientific", "science",
    "research", "researcher",
    "project", "projects",
    "system", "systems",
    "product", "products",
    "code", "coding", "program", "programming",
    "model", "modeling", "models",
    "test", "testing", "tests",
    "tool", "tools", "tooling",
    "service", "services",
    "application", "applications", "app", "apps",
    "platform", "platforms",
    "user", "users", "customer", "customers", "client", "clients",
    "business", "businesses",
    "industry", "industries",
    "world", "worldwide",
    "people", "person", "individual", "individuals",
    "time", "times",
    "level", "levels",
    "high", "low", "large", "small", "big",
    "first", "second", "last", "next", "previous",
    # additional generic filler often seen in job descriptions
    "summer", "winter", "spring", "fall", "autumn",
    "during", "across", "within", "throughout",
    "runs", "run", "running",
    "include", "includes", "including", "included",
    "across", "alongside",
    "various", "many", "several", "different", "specific",
    "task", "tasks",
    "process", "processes", "processing",
    "feature", "features",
    "use", "uses", "used", "using",
    "make", "makes", "made", "making",
    "help", "helps", "helping",
    "team", "teamwork",
    "monate", "wochen", "jahre",  # german units already captured by duration parser
}

# Regex for token extraction. Keeps alphanumerics + hyphens + plus signs
# (so "C++", "C#", "scikit-learn" survive).
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]*[A-Za-z0-9+#]|[A-Za-z]", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _bigrams(tokens: list[str]) -> list[str]:
    return [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]


def _is_useful(term: str) -> bool:
    if not term or len(term) < 3:
        return False
    if any(part in _STOPWORDS for part in term.split()):
        return False
    if term in _BANNED_TERMS:
        return False
    if any(part in _BANNED_TERMS for part in term.split()):
        return False
    if re.fullmatch(r"\d+", term):
        return False  # pure numbers
    return True


def build_idf(documents: Iterable[str]) -> dict[str, float]:
    """Document-frequency-based IDF over the corpus.

    Returns idf[term] = log((N + 1) / (df + 1)) — smoothed to avoid div-by-zero.
    """
    df: Counter[str] = Counter()
    n_docs = 0
    for d in documents:
        n_docs += 1
        tokens = _tokenize(d)
        terms = set(tokens) | set(_bigrams(tokens))
        for t in terms:
            if _is_useful(t):
                df[t] += 1
    return {t: math.log((n_docs + 1) / (f + 1)) for t, f in df.items()}


def top_corpus_terms(text: str, idf: dict[str, float], *, k: int = 6) -> list[str]:
    """Return up to k terms from `text` with the highest tf-idf weight.

    Only includes terms also present in the IDF map (i.e. seen at least once
    in the corpus). Skips terms appearing too frequently across the corpus.
    """
    if not text:
        return []
    tokens = _tokenize(text)
    terms = tokens + _bigrams(tokens)
    tf: Counter[str] = Counter(t for t in terms if _is_useful(t))
    scored: list[tuple[float, str]] = []
    for term, freq in tf.items():
        w = idf.get(term)
        # Stricter threshold than before: only surface terms that are
        # genuinely distinctive (appear in <~25% of the corpus).
        if w is None or w < 0.6:
            continue
        # Skip very short single tokens — they're rarely informative.
        if " " not in term and len(term) < 4:
            continue
        scored.append((freq * w, term))
    scored.sort(reverse=True)
    out: list[str] = []
    seen = set()
    for _, term in scored:
        # Skip if a bigram containing this unigram already chosen
        if any(term in s.split() or s in term.split() for s in seen):
            continue
        seen.add(term)
        out.append(term.title() if term.islower() and not any(c in term for c in "+#./-")
                   else term)
        if len(out) >= k:
            break
    return out
