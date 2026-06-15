"""
Celery tasks for WhatsApp template management.
"""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='templates.tasks.sync_all_tenant_templates')
def sync_all_tenant_templates():
    """
    Periodic task: sync template statuses from Meta Graph API for all
    tenants that have WhatsApp configured.

    Runs every hour via Celery Beat.
    Ensures that Meta-approved/rejected templates reflect their latest
    status in the local CachedMetaTemplate table.
    """
    from tenants.models import TenantConfig, ConfigProvider
    from templates.sync_service import sync_templates_for_tenant

    # Find all tenants that have a Meta WhatsApp access_token configured
    tenant_ids = (
        TenantConfig.objects.filter(
            provider=ConfigProvider.META_WHATSAPP,
            key_name='access_token',
            is_active=True,
        )
        .values_list('tenant_id', flat=True)
        .distinct()
    )

    from tenants.models import Tenant

    # Bulk-fetch all tenants in a single query to avoid an N+1 pattern.
    tenant_map = {t.id: t for t in Tenant.objects.filter(id__in=tenant_ids)}

    total = len(tenant_map)
    success = 0
    failed = 0

    logger.info(f"[template_sync] Starting periodic sync for {total} tenants")

    for tenant_id in tenant_map:
        try:
            tenant = tenant_map[tenant_id]
            result = sync_templates_for_tenant(tenant)
            if result.get('success'):
                success += 1
                logger.info(
                    f"[template_sync] {tenant.name}: "
                    f"{result['created']} created, {result['updated']} updated, "
                    f"{result['removed']} removed"
                )
            else:
                failed += 1
                logger.warning(
                    f"[template_sync] {tenant.name} failed: {result.get('error')}"
                )
        except Exception as e:
            failed += 1
            logger.error(f"[template_sync] Error syncing tenant {tenant_id}: {e}")

    logger.info(
        f"[template_sync] Periodic sync done — "
        f"{success}/{total} succeeded, {failed} failed"
    )
    return {'total': total, 'success': success, 'failed': failed}
