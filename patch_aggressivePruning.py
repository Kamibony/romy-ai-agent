import re

with open('extension/content/dom_mapper.js', 'r') as f:
    content = f.read()

replacement = """                // Aggressive Pruning: If the element has no meaningful text and isn't an input/button, drop it
                // Make sure to preserve elements with a Set-of-Mark ID or critical semantic containers
                let keepDueToClass = false;
                const classNameStr = typeof node.className === 'string' ? node.className : (node.className && node.className.baseVal ? node.className.baseVal : '');
                if (classNameStr) {
                    const classes = classNameStr.toLowerCase().split(/\\s+/);
                    if (classes.some(c => c.includes('dropdown') || c.includes('suggestion') || c.includes('modal') || c.includes('popup') || c.includes('menu') || c.includes('autocomplete') || c.includes('select'))) {
                        keepDueToClass = true;
                    }
                }

                if (!textContent && !isInputLike && tagName !== 'button' && tagName !== 'a' && !node.hasAttribute('data-romy-id') && tagName !== 'form' && tagName !== 'dialog' && !keepDueToClass) {
                     // If it has children, maybe it's a structural wrapper. But we want to flatten.
                     // If it's literally just an empty div/span with no aria, drop it completely.
                     return;
                }"""

pattern = r'                // Aggressive Pruning: If the element has no meaningful text and isn\'t an input/button, drop it\n                // Make sure to preserve elements with a Set-of-Mark ID or critical semantic containers\n                if \(!textContent && !isInputLike && tagName !== \'button\' && tagName !== \'a\' && !node\.hasAttribute\(\'data-romy-id\'\) && tagName !== \'form\' && tagName !== \'dialog\'\) \{\n                     // If it has children, maybe it\'s a structural wrapper\. But we want to flatten\.\n                     // If it\'s literally just an empty div/span with no aria, drop it completely\.\n                     return;\n                \}'

def replacer(match):
    return replacement.replace('\\\\s+', '\\s+')

new_content = re.sub(pattern, replacer, content)

with open('extension/content/dom_mapper.js', 'w') as f:
    f.write(new_content)
