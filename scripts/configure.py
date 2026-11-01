"""Create private development configuration outside the repository without echoing secrets."""

import argparse
import getpass
from pathlib import Path
import secrets

parser = argparse.ArgumentParser()
parser.add_argument(
    "--output",
    required=True,
    help="Path outside the repository to a new private environment file",
)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[1]
target = Path(args.output).resolve()
if target.is_relative_to(repo):
    raise SystemExit("Choose an environment file outside the source checkout.")
if target.exists():
    raise SystemExit("Refusing to overwrite an existing environment file.")
values = {
    name: secrets.token_hex(32)
    for name in (
        "SESSION_SECRET",
        "INTERNAL_SECRET",
        "BANK_WRITE_SECRET",
        "POSTGRES_PASSWORD",
        "RABBIT_PASSWORD",
    )
}
values["GROQ_API_KEY"] = getpass.getpass(
    "Groq API key (hidden; Enter for deterministic views only): "
).strip()
values["VOYAGE_API_KEY"] = getpass.getpass(
    "Voyage API key (hidden; Enter for policy text search): "
).strip()
values.update(
    LLM_MODEL="groq/openai/gpt-oss-120b",
    LLM_FALLBACK_MODEL="groq/qwen/qwen3.8-27b",
    LLM_MAX_TOKENS="1024",
    LLM_TIMEOUT_SECONDS="60",
    LLM_MAX_RETRIES="2",
    EMBEDDING_MODEL="voyage/voyage-3.5",
    EMBEDDING_DIM="1024",
)
if any("\n" in value or "\r" in value for value in values.values()):
    raise SystemExit("Invalid multiline configuration value.")
target.parent.mkdir(parents=True, exist_ok=True)
with target.open("x", encoding="utf-8") as output:
    output.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
target.chmod(0o600)
print(
    "Private configuration created. On Windows, restrict its ACL to your user account."
)
