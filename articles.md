---
layout: page
title: Articles
---

# Articles

## Articles and Documentation

In addition to world files, the site includes a small but growing collection of **articles and reference material**, including:

- Cleaned-up and preserved content originally sourced from the now-abandoned Eden Wiki  
- Write-ups on notable worlds and in-game features  

Planned future additions include:

- Guides (e.g. backing up your own worlds, importing worlds correctly)  
- Technical notes and preservation documentation  
- Links to other Eden-related community projects  

## List of articles

Under Construction!

{% assign sorted_articles = site.articles | sort: "title" %}
<ul>
  {% for article in sorted_articles %}
    <li>
      <a href="{{ article.url }}">{{ article.title }}</a>
      {% if article.date %}<small>({{ article.date | date: "%Y-%m-%d" }})</small>{% endif %}
    </li>
  {% endfor %}
</ul>

