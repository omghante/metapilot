"""
Meta Template Sync Service.

Fetches ALL templates from Meta Graph API (handling pagination),
classifies them, and stores in CachedMetaTemplate for fast querying.
"""
import logging
from typing import Dict, Any, Optional, List
from django.utils import timezone
from django.db import transaction
from django.conf import settings

from templates.models import CachedMetaTemplate
from templates.classifier import classify_template, extract_template_metadata
from templates.meta_service import MetaTemplateService

logger = logging.getLogger(__name__)


def sync_templates_for_tenant(tenant) -> Dict[str, Any]:
    """
    Fetch ALL templates from Meta Graph API for a tenant and cache them.
    
    - Handles cursor-based pagination (fetches all pages)
    - Classifies each template (industry, feature_group, use_case)
    - Extracts component metadata (header, buttons, body_text)
    - Upserts into CachedMetaTemplate
    - Removes templates that no longer exist in Meta
    
    Returns:
        Dict with sync stats: created, updated, removed, total, errors
    """
    service = MetaTemplateService(tenant)
    
    if not service.is_configured:
        return {
            'success': False,
            'error': 'WhatsApp Business Account not configured',
            'created': 0, 'updated': 0, 'removed': 0, 'total': 0,
        }
    
    all_templates = []
    after_cursor = None
    page_count = 0
    max_pages = 50  # Safety limit
    
    # Fetch all pages
    while page_count < max_pages:
        page_count += 1
        result = service.fetch_templates(limit=100, after=after_cursor)
        
        if not result['success']:
            logger.error(f"Sync failed for {tenant.name} on page {page_count}: {result.get('error')}")
            if page_count == 1:
                # First page failed — nothing to sync
                return {
                    'success': False,
                    'error': result.get('error', 'Unknown error'),
                    'created': 0, 'updated': 0, 'removed': 0, 'total': 0,
                }
            # Partial fetch — use what we have
            break
        
        templates = result.get('templates', [])
        all_templates.extend(templates)
        
        # Check for next page
        paging = result.get('paging', {})
        if paging.get('next') and paging.get('cursors', {}).get('after'):
            after_cursor = paging['cursors']['after']
        else:
            break
    
    logger.info(f"Fetched {len(all_templates)} templates from Meta for {tenant.name} ({page_count} pages)")
    
    # Process and upsert
    stats = {'created': 0, 'updated': 0, 'removed': 0, 'total': len(all_templates), 'errors': []}
    seen_keys = set()  # Track (meta_template_id, language) combos
    
    with transaction.atomic():
        for tmpl in all_templates:
            try:
                meta_id = str(tmpl.get('id', ''))
                name = tmpl.get('name', '')
                language = tmpl.get('language', 'en_US')
                category = tmpl.get('category', 'UTILITY')
                status = tmpl.get('status', 'PENDING')
                components = tmpl.get('components', [])
                quality_score_data = tmpl.get('quality_score', {})
                quality_score = quality_score_data.get('score', '') if isinstance(quality_score_data, dict) else str(quality_score_data)
                rejected_reason = tmpl.get('rejected_reason', '') or ''
                
                # Extract metadata from components
                metadata = extract_template_metadata(components)
                
                # Classify template
                classification = classify_template(
                    name=name,
                    category=category,
                    body_text=metadata.get('body_text', '')
                )
                
                key = (meta_id, language)
                seen_keys.add(key)
                
                # Upsert
                obj, created = CachedMetaTemplate.objects.update_or_create(
                    tenant=tenant,
                    meta_template_id=meta_id,
                    language=language,
                    defaults={
                        'name': name,
                        'status': status,
                        'category': category,
                        'components': components,
                        'quality_score': quality_score,
                        'rejected_reason': rejected_reason,
                        'industry': classification.get('industry', ''),
                        'feature_group': classification.get('feature_group', ''),
                        'use_case': classification.get('use_case', ''),
                        'has_header': metadata.get('has_header', False),
                        'header_format': metadata.get('header_format', ''),
                        'has_buttons': metadata.get('has_buttons', False),
                        'button_count': metadata.get('button_count', 0),
                        'body_text': metadata.get('body_text', ''),
                    }
                )
                
                if created:
                    stats['created'] += 1
                else:
                    stats['updated'] += 1
                    
            except Exception as e:
                error_msg = f"Error processing template {tmpl.get('name', '?')}: {e}"
                logger.error(error_msg)
                stats['errors'].append(error_msg)
        
        # Remove templates no longer in Meta
        existing = CachedMetaTemplate.objects.filter(tenant=tenant)
        for cached in existing:
            key = (cached.meta_template_id, cached.language)
            if key not in seen_keys:
                cached.delete()
                stats['removed'] += 1
    
    stats['success'] = True
    logger.info(
        f"Sync complete for {tenant.name}: "
        f"{stats['created']} created, {stats['updated']} updated, "
        f"{stats['removed']} removed, {stats['total']} total"
    )
    
    return stats


def get_filter_counts(tenant) -> Dict[str, Any]:
    """
    Calculate dynamic filter counts for the template library sidebar.
    
    Returns counts grouped by: category, status, industry, feature_group, language
    """
    from django.db.models import Count
    
    qs = CachedMetaTemplate.objects.filter(tenant=tenant)
    
    def _count_field(field_name):
        """Get value counts for a field, excluding empty values."""
        return dict(
            qs.exclude(**{field_name: ''})
            .values_list(field_name)
            .annotate(count=Count('id'))
            .order_by(field_name)
        )
    
    # Group use_cases by feature_group
    feature_use_cases = {}
    fg_uc_data = (
        qs.exclude(feature_group='')
        .exclude(use_case='')
        .values('feature_group', 'use_case')
        .annotate(count=Count('id'))
        .order_by('feature_group', 'use_case')
    )
    for row in fg_uc_data:
        fg = row['feature_group']
        if fg not in feature_use_cases:
            feature_use_cases[fg] = {}
        feature_use_cases[fg][row['use_case']] = row['count']
    
    return {
        'category': _count_field('category'),
        'status': _count_field('status'),
        'industry': _count_field('industry'),
        'feature_group': _count_field('feature_group'),
        'language': _count_field('language'),
        'feature_use_cases': feature_use_cases,
        'total': qs.count(),
    }
