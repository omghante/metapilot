# Database Engineering

All database-related artifacts for MetaPilot: schema, migrations, seeds, config, and maintenance scripts.

---

## Structure

```
database/
├── config/           PostgreSQL connection and tuning configs
├── schema/           ERD, table definitions, index strategy
├── migrations/       Version-controlled raw SQL migration history
├── seeds/            Dev and test seed data
├── scripts/          Backup, restore, migrate shell scripts
└── security/         Roles, permissions, encryption docs
```

---

## Quick Reference

```bash
# Apply latest migration
bash database/scripts/migrate.sh

# Backup production DB
bash database/scripts/backup.sh

# Restore from backup
bash database/scripts/restore.sh <backup_file>

# Seed development data
bash database/scripts/seed.sh
```

See [schema/tables.sql](./schema/tables.sql) for the full table definitions.
