-- MetaPilot — PostgreSQL initial schema
-- Generated: 2026-05-25
-- Run via: psql $DATABASE_URL < database/schema/tables.sql

-- ── Extensions ──────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- for ILIKE search

-- ── Users ────────────────────────────────────────────────────
-- Managed by Django auth + users app
-- Table: users_user

-- ── Tenants ──────────────────────────────────────────────────
-- Table: tenants_agency
-- Table: tenants_tenant
-- Table: tenants_whatsappconfig  (tokens encrypted via Fernet)
-- Table: tenants_auditlog

-- ── Contacts ─────────────────────────────────────────────────
-- Table: messaging_contact          (phone, name, tags JSONB, is_subscribed)
-- Table: messaging_message          (direction, type, status, wamid)
-- Table: messaging_messagelog       (delivery events)

-- ── Campaigns ────────────────────────────────────────────────
-- Table: campaigns_campaign         (status, template_name, target_all, target_tags)
-- Table: campaigns_campaignmessage  (individual scheduled message within campaign)
-- Table: campaigns_scheduledmessage (contact-level delivery tracking)
-- Table: campaigns_messageresult    (final delivery outcome)

-- ── Templates ────────────────────────────────────────────────
-- Table: templates_whatsapptemplate    (agency-managed templates)
-- Table: templates_cachedmetatemplate  (synced from Meta Graph API)
-- Table: templates_templatecomponent   (header/body/footer/buttons)

-- ── Scheduler ────────────────────────────────────────────────
-- Table: scheduler_schedulerjob         (job: tenant, template, scheduled_time, status)
-- Table: scheduler_schedulerjobrecipient (per-contact delivery status)
-- Table: scheduler_schedulerlog         (heartbeat and run logs)

-- ── Inbox ─────────────────────────────────────────────────────
-- Table: inbox_conversation    (contact ↔ tenant thread)
-- Table: inbox_inboxmessage    (individual message in thread)

-- ── WA Chatbot ───────────────────────────────────────────────
-- Table: wa_chatbot_wachatbotsession   (per-contact session)
-- Table: wa_chatbot_sessionmessage     (history entries)
-- Table: wa_chatbot_knowledgedocument  (RAG knowledge base)

-- ── Notifications ─────────────────────────────────────────────
-- Table: notifications_notification   (recipient, type, read, metadata JSONB)

-- ── Billing ──────────────────────────────────────────────────
-- Table: billing_plan           (Free / Pro / Enterprise)
-- Table: billing_subscription   (tenant → plan, active period)
-- Table: billing_usagerecord    (per-tenant monthly usage counter)
