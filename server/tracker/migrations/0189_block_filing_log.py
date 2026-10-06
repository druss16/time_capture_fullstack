"""
A change log of filing-relevant Block writes, kept by a trigger.

The learned-folder index (services/matter_attribution.py) used to re-read 180
days of filed blocks on every attribution tick. It now keeps the index and folds
in only what changed, which needs to know WHAT changed — and project_id is
written by a dozen paths, several of them bulk .update() calls that bypass
signals and auto_now. A trigger sees all of them.

The folder rules stay in Python (folder_key); the trigger only records which
block changed and whether the change can only ADD to the index ('a': the row
contributed nothing before) or might also remove something ('o': re-file,
unfile, path/start change, soft or hard delete). 'o' makes the reader rebuild.

xid is the writing transaction, so a reader can take exactly the entries its
previous snapshot could not see — a serial id alone would skip entries whose
transaction committed out of order.

Needs PostgreSQL 13+ (xid8 / pg_current_xact_id). Until this is applied the
reader falls back to the full rebuild, so code may ship ahead of it.
"""
from django.db import migrations

# A row contributes to the index iff it is filed, has a path, and is live.
_CONTRIBUTED = "(OLD.project_id IS NOT NULL AND OLD.file_path <> '' AND OLD.deleted_at IS NULL)"

FORWARD = f"""
CREATE TABLE tracker_blockfilinglog (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL,
    block_id bigint NOT NULL,
    kind char(1) NOT NULL,
    xid xid8 NOT NULL DEFAULT pg_current_xact_id(),
    at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX tracker_blockfilinglog_org_xid ON tracker_blockfilinglog (org_id, xid);
CREATE INDEX tracker_blockfilinglog_at ON tracker_blockfilinglog (at);

CREATE FUNCTION tracker_block_filing_log() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO tracker_blockfilinglog (org_id, block_id, kind) VALUES (NEW.org_id, NEW.id, 'a');
        RETURN NULL;
    END IF;
    IF TG_OP = 'DELETE' THEN
        INSERT INTO tracker_blockfilinglog (org_id, block_id, kind) VALUES (OLD.org_id, OLD.id, 'o');
        RETURN NULL;
    END IF;
    IF NOT {_CONTRIBUTED} THEN
        INSERT INTO tracker_blockfilinglog (org_id, block_id, kind) VALUES (NEW.org_id, NEW.id, 'a');
    ELSE
        INSERT INTO tracker_blockfilinglog (org_id, block_id, kind) VALUES (OLD.org_id, OLD.id, 'o');
        IF NEW.org_id IS DISTINCT FROM OLD.org_id THEN
            INSERT INTO tracker_blockfilinglog (org_id, block_id, kind) VALUES (NEW.org_id, NEW.id, 'o');
        END IF;
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER tracker_block_filing_log_ins AFTER INSERT ON tracker_block
    FOR EACH ROW WHEN (NEW.project_id IS NOT NULL)
    EXECUTE FUNCTION tracker_block_filing_log();

CREATE TRIGGER tracker_block_filing_log_upd AFTER UPDATE ON tracker_block
    FOR EACH ROW WHEN (
        (OLD.project_id IS NOT NULL OR NEW.project_id IS NOT NULL)
        AND (OLD.project_id IS DISTINCT FROM NEW.project_id
             OR OLD.file_path IS DISTINCT FROM NEW.file_path
             OR OLD.start IS DISTINCT FROM NEW.start
             OR OLD.deleted_at IS DISTINCT FROM NEW.deleted_at
             OR OLD.org_id IS DISTINCT FROM NEW.org_id)
    )
    EXECUTE FUNCTION tracker_block_filing_log();

CREATE TRIGGER tracker_block_filing_log_del AFTER DELETE ON tracker_block
    FOR EACH ROW WHEN {_CONTRIBUTED}
    EXECUTE FUNCTION tracker_block_filing_log();
"""

REVERSE = """
DROP TRIGGER IF EXISTS tracker_block_filing_log_del ON tracker_block;
DROP TRIGGER IF EXISTS tracker_block_filing_log_upd ON tracker_block;
DROP TRIGGER IF EXISTS tracker_block_filing_log_ins ON tracker_block;
DROP FUNCTION IF EXISTS tracker_block_filing_log();
DROP TABLE IF EXISTS tracker_blockfilinglog;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0188_social_login'),
    ]

    operations = [
        migrations.RunSQL(FORWARD, REVERSE),
    ]
