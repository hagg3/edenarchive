---
layout: page
title: Blog
permalink: /blog/
---
<ul class="post-list">
  {% for post in site.posts %}
    <li>
      <h2>
        <a href="{{ post.url | relative_url }}">
          {{ post.title }}
        </a>
      </h2>

      <p class="post-meta">
        {{ post.date | date: "%B %-d, %Y" }}
        {% if post.author %}
          • {{ post.author }}
        {% endif %}
      </p>
    </li>
  {% endfor %}
</ul>
