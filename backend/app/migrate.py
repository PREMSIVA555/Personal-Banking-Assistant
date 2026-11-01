from pathlib import Path
from psycopg.types.json import Jsonb
from .config import settings
from .db import db
from .security import password_hash

POLICIES = [
    (
        "policy-disputes",
        "Disputing an unrecognized transaction",
        "For this synthetic demo bank, a customer may report an unrecognized posted debit within 60 days. Select the transaction and explain why you do not recognize it. Review and explicitly confirm before submission. A submitted dispute is a request for investigation, not a refund or a decision. Pending transactions cannot be disputed yet.",
    ),
    (
        "policy-timing",
        "What happens after a dispute is submitted?",
        "The synthetic bank returns a case reference once it receives a dispute. The initial status is received. The demo does not investigate claims or issue refunds. If submission cannot be verified, the request remains under verification and may require manual review. Do not submit the same transaction repeatedly.",
    ),
    (
        "policy-privacy",
        "Your information and this development demo",
        "Aurora is a synthetic banking demonstration. All seeded customers, accounts, and merchants are fictional. Chat text and retrieved synthetic information may be sent to Groq; policy queries and sample policy documents may be sent to Voyage. Do not enter real account details, passwords, identity documents, or personal financial information.",
    ),
    (
        "policy-services",
        "Available banking services",
        "This first demo supports balance enquiries, transaction search, dispute preparation and tracking, and support handoff. Statement generation, address changes, cheque-book requests, and KYC intake are planned features and are not available. A support case does not imply that any staff member has been notified outside this demo.",
    ),
]


def migrate():
    s = settings()
    with db() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(81624411)")
        # Only a validated integer enters DDL. Never interpolate user data into SQL.
        ddl = (
            (Path(__file__).parents[1] / "schema.sql")
            .read_text()
            .replace("{embedding_dim}", str(s.embedding_dim))
        )
        conn.execute(ddl)
        for key, value in [
            ("embedding_dim", str(s.embedding_dim)),
            ("embedding_model", s.embedding_model),
        ]:
            old = conn.execute(
                "SELECT value FROM schema_meta WHERE key=%s", (key,)
            ).fetchone()
            if old and old["value"] != value:
                raise RuntimeError(
                    f"{key} differs from existing embeddings. Use a reviewed reindex migration or a new development volume."
                )
            conn.execute(
                "INSERT INTO schema_meta VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (key, value),
            )
        for uid, name, email in [
            ("customer-ava", "Ava Morgan", "ava@demo.bank"),
            ("customer-noah", "Noah Patel", "noah@demo.bank"),
        ]:
            conn.execute(
                "INSERT INTO customers VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (uid, name, email, password_hash("DemoBank!2026")),
            )
        for values in [
            (
                "acc-ava-main",
                "customer-ava",
                "Everyday account",
                "4821",
                12845075,
                "INR",
            ),
            (
                "acc-ava-save",
                "customer-ava",
                "Savings account",
                "9306",
                35420000,
                "INR",
            ),
            (
                "acc-noah-main",
                "customer-noah",
                "Everyday account",
                "1659",
                6412000,
                "INR",
            ),
        ]:
            conn.execute(
                "INSERT INTO accounts VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                values,
            )
        for tid, account, merchant, amount, days, category in [
            ("txn-example", "acc-ava-main", "Example Store", -249900, 2, "Shopping"),
            ("txn-grocer", "acc-ava-main", "Green Basket", -184050, 1, "Groceries"),
            ("txn-salary", "acc-ava-main", "Northstar Payroll", 8500000, 5, "Income"),
            ("txn-cafe", "acc-ava-main", "Sunday Coffee", -42000, 3, "Food & drink"),
            ("txn-metro", "acc-ava-main", "Metro Transit", -15000, 4, "Transport"),
            (
                "txn-subscription",
                "acc-ava-main",
                "Cloud Notes",
                -49900,
                6,
                "Subscriptions",
            ),
            ("txn-interest", "acc-ava-save", "Monthly interest", 185000, 7, "Income"),
            (
                "txn-noah",
                "acc-noah-main",
                "Noah Private Merchant",
                -99000,
                2,
                "Shopping",
            ),
        ]:
            conn.execute(
                "INSERT INTO transactions(id,account_id,merchant,amount_minor,currency,posted_at,category) VALUES (%s,%s,%s,%s,'INR',now()-(%s * interval '1 day'),%s) ON CONFLICT DO NOTHING",
                (tid, account, merchant, amount, days, category),
            )
        for pid, title, content in POLICIES:
            conn.execute(
                "INSERT INTO memories(id,kind,title,content,version,effective_from,embedding_model,approved) VALUES (%s,'approved_policy',%s,%s,'demo-1',DATE '2026-01-01',%s,true) ON CONFLICT DO NOTHING",
                (pid, title, content, s.embedding_model),
            )


if __name__ == "__main__":
    migrate()
    print(
        "Schema and synthetic fixtures ready; embedding schema matches configuration."
    )
