-- MetaPilot — Performance Indexes
-- Applied on top of Django auto-created primary key indexes

-- contacts: fast lookup by phone + tenant
CREATE INDEX IF NOT EXISTS idx_contact_phone_tenant
    ON messaging_contact (tenant_id, phone);

-- contacts: tag search (GIN for JSONB)
CREATE INDEX IF NOT EXISTS idx_contact_tags
    ON messaging_contact USING GIN (tags);

-- campaigns: status filter
CREATE INDEX IF NOT EXISTS idx_campaign_status
    ON campaigns_campaign (tenant_id, status);

-- scheduler jobs: polling (due jobs)
CREATE INDEX IF NOT EXISTS idx_schedulerjob_due
    ON scheduler_schedulerjob (scheduled_time, status)
    WHERE status = 'pending';

-- scheduler recipients: status per job
CREATE INDEX IF NOT EXISTS idx_recipient_job_status
    ON scheduler_schedulerjobrecipient (job_id, status);

-- inbox conversations: recent activity
CREATE INDEX IF NOT EXISTS idx_conversation_tenant_updated
    ON inbox_conversation (tenant_id, updated_at DESC);

-- inbox messages: conversation thread
CREATE INDEX IF NOT EXISTS idx_inboxmessage_conversation
    ON inbox_inboxmessage (conversation_id, created_at DESC);

-- cached templates: lookup by name + tenant
CREATE INDEX IF NOT EXISTS idx_cachedtemplate_name_tenant
    ON templates_cachedmetatemplate (tenant_id, name, status);

-- audit log: recent actions per tenant
CREATE INDEX IF NOT EXISTS idx_auditlog_tenant_created
    ON tenants_auditlog (tenant_id, created_at DESC);

-- notifications: unread per user
CREATE INDEX IF NOT EXISTS idx_notification_user_unread
    ON notifications_notification (recipient_id, is_read)
    WHERE is_read = false;
