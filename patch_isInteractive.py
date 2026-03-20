import re

with open('extension/content/dom_mapper.js', 'r') as f:
    content = f.read()

replacement = """        function isInteractive(el) {
            if (el.matches(locators)) return true;

            // Check for interactive ARIA states and properties
            if (el.hasAttribute('aria-haspopup') || el.hasAttribute('aria-expanded') || el.hasAttribute('aria-pressed')) {
                return true;
            }

            // Check ARIA attributes
            if (el.hasAttribute('aria-label') || el.hasAttribute('role')) {
                const role = el.getAttribute('role');
                if (['button', 'link', 'menuitem', 'tab', 'checkbox', 'radio', 'switch', 'combobox', 'textbox', 'searchbox', 'widget', 'slider', 'spinbutton', 'listbox', 'option', 'gridcell', 'treeitem'].includes(role)) {
                    return true;
                }
                // If it has aria-label and isn't just a generic container
                if (el.hasAttribute('aria-label') && (el.tagName !== 'DIV' && el.tagName !== 'SPAN' || el.hasAttribute('tabindex'))) {
                    return true;
                }
            }

            // Explicitly preserve elements with direct text content (e.g. dropdown list items)
            for (let i = 0; i < el.childNodes.length; i++) {
                if (el.childNodes[i].nodeType === Node.TEXT_NODE && el.childNodes[i].textContent.trim().length > 0) {
                    return true;
                }
            }

            // Check common structural action classes (handling SVG className objects)
            const className = typeof el.className === 'string' ? el.className : (el.className && el.className.baseVal ? el.className.baseVal : '');
            if (className) {
                const classes = className.toLowerCase().split(/\\s+/);
                // Require exact matches or strict prefixes/suffixes to prevent vacuuming structural wrappers (e.g., 'action-bar', 'submit-container')
                if (classes.some(c => c === 'btn' || c === 'button' || c.endsWith('-btn') || c.endsWith('-button') || c.startsWith('btn-') || c === 'submit' || c.includes('datepicker') || c.endsWith('-input') || c.includes('dropdown') || c.includes('suggestion') || c.includes('modal') || c.includes('popup') || c.includes('menu') || c.includes('autocomplete') || c.includes('select'))) {
                    return true;
                }
            }

            return false;
        }"""

pattern = r'        function isInteractive\(el\) \{[\s\S]*?return false;\n        \}'
# we use an inline replace to avoid bad escapes.

def replacer(match):
    return replacement.replace('\\\\s+', '\\s+')

new_content = re.sub(pattern, replacer, content)

with open('extension/content/dom_mapper.js', 'w') as f:
    f.write(new_content)
