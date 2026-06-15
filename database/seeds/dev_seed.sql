-- MetaPilot — Development Seed Data
-- Usage: psql $DATABASE_URL < database/seeds/dev_seed.sql
-- WARNING: Never run against production

-- Agency
INSERT INTO tenants_agency (id, name, slug, created_at)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'Demo Agency',
    'demo-agency',
    NOW()
) ON CONFLICT DO NOTHING;

-- Tenant
INSERT INTO tenants_tenant (id, agency_id, name, slug, created_at)
VALUES (
    '00000000-0000-0000-0000-000000000002',
    '00000000-0000-0000-0000-000000000001',
    'Demo Business',
    'demo-business',
    NOW()
) ON CONFLICT DO NOTHING;

-- Sample contacts (no real phone numbers)
INSERT INTO messaging_contact (id, tenant_id, name, phone, is_subscribed, is_blocked, tags, created_at)
VALUES
    (gen_random_uuid(), '00000000-0000-0000-0000-000000000002', 'Alice Dev', '+10000000001', true, false, '["vip", "new"]', NOW()),
    (gen_random_uuid(), '00000000-0000-0000-0000-000000000002', 'Bob Test',  '+10000000002', true, false, '["regular"]', NOW()),
    (gen_random_uuid(), '00000000-0000-0000-0000-000000000002', 'Carol QA',  '+10000000003', true, false, '["vip"]', NOW())
ON CONFLICT DO NOTHING;
