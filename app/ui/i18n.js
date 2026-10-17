'use strict';

(() => {
  const catalogs = window.PriveltoTranslations;
  const supported = Object.keys(catalogs);
  let language = 'es';
  const textNodes = [];
  const attributes = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.parentElement.closest('script, style, #interfaceLanguage') && node.textContent.trim()) {
      textNodes.push([node, node.textContent]);
    }
  }
  for (const element of document.querySelectorAll('[title], [aria-label], [placeholder]')) {
    for (const name of ['title', 'aria-label', 'placeholder']) {
      if (element.hasAttribute(name)) attributes.push([element, name, element.getAttribute(name)]);
    }
  }
  const patterns = Object.keys(catalogs.es.messages).filter((key) => /\{\d+\}/.test(key)).map((key) => {
    const indexes = [];
    const pattern = key.split(/(\{\d+\})/).map((part) => {
      if (/^\{\d+\}$/.test(part)) { indexes.push(Number(part.slice(1, -1))); return '([\\s\\S]*?)'; }
      return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }).join('');
    return { key, indexes, expression: new RegExp('^' + pattern + '$') };
  }).sort((first, second) => second.key.length - first.key.length);

  function format(template, values) {
    return template.replace(/\{(\d+)\}/g, (match, index) => index < values.length ? String(values[index]) : match);
  }
  function t(message, ...values) {
    const source = String(message ?? '');
    const messages = catalogs[language].messages;
    if (Object.hasOwn(messages, source)) return format(messages[source], values);
    if (values.length) return format(source, values);
    const trimmed = source.trim();
    if (Object.hasOwn(messages, trimmed)) return source.replace(trimmed, messages[trimmed]);
    // Only UI messages are passed here. Document values, paths and tokens are never translated.
    for (const pattern of patterns) {
      const match = pattern.expression.exec(source);
      if (!match) continue;
      const captured = [];
      pattern.indexes.forEach((index, position) => { captured[index] = match[position + 1]; });
      return format(messages[pattern.key] || pattern.key, captured);
    }
    return source;
  }
  function apply(selected) {
    language = supported.includes(selected) ? selected : 'en';
    document.documentElement.lang = language;
    for (const [node, source] of textNodes) if (node.isConnected) node.textContent = t(source);
    for (const [element, name, source] of attributes) if (element.isConnected) element.setAttribute(name, t(source));
    document.getElementById('interfaceLanguage').value = language;
  }
  window.PriveltoI18n = { t, apply, get language() { return language; }, supported };
})();
