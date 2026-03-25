def calculate_match_score(item, claim_description):
    """
    Calculate how well a student's claim matches a found item.
    Returns a score from 0 to 100.

    Scoring:
    - Keyword overlap between claim and item description: up to 40 points
    - Category mention in claim: 30 points
    - Location mention in claim: 20 points
    - Date proximity mention: 10 points
    """
    score = 0
    claim_lower = claim_description.lower()
    item_desc_lower = item['description'].lower()

    # --- Keyword matching (up to 40 points) ---
    item_keywords = set(item_desc_lower.split())
    claim_keywords = set(claim_lower.split())
    # Remove common stop words
    stop_words = {'the', 'a', 'an', 'is', 'it', 'my', 'i', 'was', 'in', 'on',
                  'at', 'to', 'and', 'or', 'of', 'with', 'for', 'that', 'this',
                  'have', 'has', 'had', 'lost', 'found', 'item'}
    item_keywords -= stop_words
    claim_keywords -= stop_words

    if item_keywords:
        overlap = item_keywords & claim_keywords
        keyword_ratio = len(overlap) / len(item_keywords)
        score += int(keyword_ratio * 40)

    # --- Category match (30 points) ---
    category_lower = item['category'].lower()
    if category_lower in claim_lower:
        score += 30
    else:
        # Partial: check if any word of category appears
        cat_words = category_lower.split()
        for word in cat_words:
            if len(word) > 2 and word in claim_lower:
                score += 15
                break

    # --- Location match (20 points) ---
    location_lower = item['location_found'].lower()
    if location_lower in claim_lower:
        score += 20
    else:
        loc_words = location_lower.split()
        for word in loc_words:
            if len(word) > 2 and word in claim_lower:
                score += 10
                break

    # --- Date mention (10 points) ---
    if item['date_found'] in claim_description:
        score += 10

    return min(score, 100)


def find_matching_items(lost_report, found_items):
    """
    Given a student's lost report, find found items that might match.
    Returns list of (item, score) tuples sorted by score descending.
    """
    matches = []
    for item in found_items:
        score = 0
        report_desc = lost_report['description'].lower()
        item_desc = item['description'].lower()

        # Category match
        if lost_report['category'].lower() == item['category'].lower():
            score += 35

        # Keyword overlap
        report_words = set(report_desc.split()) - {'the', 'a', 'an', 'is', 'it', 'my', 'i'}
        item_words = set(item_desc.split()) - {'the', 'a', 'an', 'is', 'it', 'my', 'i'}
        if report_words:
            overlap = report_words & item_words
            score += int((len(overlap) / max(len(report_words), 1)) * 35)

        # Location similarity
        if lost_report['location_lost'].lower() == item['location_found'].lower():
            score += 20
        elif lost_report['location_lost'].lower() in item['location_found'].lower():
            score += 10

        # Title similarity
        title_words_r = set(lost_report['title'].lower().split())
        title_words_i = set(item['title'].lower().split())
        if title_words_r & title_words_i:
            score += 10

        if score >= 30:
            matches.append((item, min(score, 100)))

    matches.sort(key=lambda x: x[1], reverse=True)
    return matches


def generate_ai_description(filename):
    """
    Generate a simple description of an uploaded image based on filename
    and common patterns. In a production system, this would call a real
    AI vision API (e.g., Claude Vision API).

    For the IA, this demonstrates the concept of AI-assisted cataloguing.
    """
    name = filename.lower().rsplit('.', 1)[0] if '.' in filename else filename.lower()
    name = name.replace('_', ' ').replace('-', ' ')

    # Category detection from common item keywords
    categories = {
        'phone': 'A mobile phone/smartphone device',
        'laptop': 'A laptop computer',
        'bottle': 'A water bottle or drink container',
        'bag': 'A bag or backpack',
        'book': 'A book or notebook',
        'pen': 'A pen or writing instrument',
        'pencil': 'A pencil or writing instrument',
        'glasses': 'A pair of glasses or spectacles',
        'key': 'A key or set of keys',
        'wallet': 'A wallet or purse',
        'watch': 'A wristwatch',
        'headphone': 'Headphones or earbuds',
        'earbud': 'Earbuds or in-ear headphones',
        'charger': 'A device charger or cable',
        'jacket': 'A jacket or outerwear',
        'sweater': 'A sweater or jumper',
        'uniform': 'A school uniform piece',
        'calculator': 'A calculator',
        'usb': 'A USB drive or flash storage',
        'umbrella': 'An umbrella',
    }

    for keyword, desc in categories.items():
        if keyword in name:
            return f"{desc}. Uploaded as '{filename}'."

    return f"An item uploaded as '{filename}'. Please add a manual description for better matching."
