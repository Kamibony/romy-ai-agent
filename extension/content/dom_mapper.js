// Global namespace to export functions to the Content Script
window.RomyDomMapper = {
    extractUIElements: function() {
        console.log("Romy DOM Mapper initialized. Injecting and extracting structural UI array.");
        const elements = [];
        let elementIdCounter = 0;

        // Note: We explicitly do NOT skip DOM mapping based on document.visibilityState
        // because the Python backend often drives Chrome in the background, causing
        // visibilityState to be 'hidden', which would result in an empty payload.

        // Broad locator string matching Playwright scanning
        const locators = 'button, a, input, select, textarea, [role="button"], [role="link"], [role="menuitem"], [role="tab"], [role="checkbox"], [role="radio"], [role="switch"], [onclick]';

        function isInteractive(el) {
            if (el.matches(locators)) return true;

            // Check ARIA attributes
            if (el.hasAttribute('aria-label') || el.hasAttribute('role')) {
                const role = el.getAttribute('role');
                if (['button', 'link', 'menuitem', 'tab', 'checkbox', 'radio', 'switch'].includes(role)) {
                    return true;
                }
                // If it has aria-label and isn't just a generic container
                if (el.hasAttribute('aria-label') && (el.tagName !== 'DIV' && el.tagName !== 'SPAN' || el.hasAttribute('tabindex'))) {
                    return true;
                }
            }

            // Check common structural action classes (handling SVG className objects)
            const className = typeof el.className === 'string' ? el.className : (el.className && el.className.baseVal ? el.className.baseVal : '');
            if (className) {
                const classes = className.toLowerCase().split(/\s+/);
                // Require exact matches or strict prefixes/suffixes to prevent vacuuming structural wrappers (e.g., 'action-bar', 'submit-container')
                if (classes.some(c => c === 'btn' || c === 'button' || c.endsWith('-btn') || c.endsWith('-button') || c.startsWith('btn-') || c === 'submit')) {
                    return true;
                }
            }

            return false;
        }

        function getAllNodes(root) {
            let nodes = [];
            const elements = root.querySelectorAll('*');
            elements.forEach(el => {
                if (isInteractive(el)) {
                    nodes.push(el);
                }
                if (el.shadowRoot) {
                    nodes = nodes.concat(getAllNodes(el.shadowRoot));
                }
            });
            return nodes;
        }

        function getXPath(element) {
            if (!element) return '';
            const id = element.getAttribute ? element.getAttribute('id') : null;
            if (id) {
                return 'id("' + id + '")';
            }
            if (element === document.body) {
                return element.tagName.toLowerCase();
            }
            if (!element.parentNode) {
                return '';
            }

            var ix = 0;
            var siblings = element.parentNode.childNodes;
            for (var i = 0; i < siblings.length; i++) {
                var sibling = siblings[i];
                if (sibling === element) {
                    const parentXPath = getXPath(element.parentNode);
                    if (!parentXPath) return '';
                    return parentXPath + '/' + element.tagName.toLowerCase() + '[' + (ix + 1) + ']';
                }
                if (sibling.nodeType === 1 && sibling.tagName === element.tagName) {
                    ix++;
                }
            }
            return '';
        }

        const allNodes = getAllNodes(document);

        allNodes.forEach((node) => {
            const rect = node.getBoundingClientRect();

            // Simplified visibility check
            const computedStyle = window.getComputedStyle(node);

            // Allow elements that are partially visible / slightly out of viewport bounds
            // Add a buffer of 50px for elements that might be slightly scrolled out of view but still relevant
            const BUFFER = 50;

            let isVisible = (
                rect.width > 0 &&
                rect.height > 0 &&
                rect.bottom > -BUFFER && // Element's bottom edge is below top of viewport
                rect.top < (window.innerHeight || document.documentElement.clientHeight) + BUFFER && // Top edge is above bottom of viewport
                rect.right > -BUFFER && // Right edge is past left side
                rect.left < (window.innerWidth || document.documentElement.clientWidth) + BUFFER && // Left edge is before right side
                computedStyle.visibility !== 'hidden' &&
                computedStyle.display !== 'none' &&
                computedStyle.opacity !== '0' &&
                parseFloat(computedStyle.opacity) > 0.05 // Ignore elements that are basically invisible
            );

            // Relax visibility checks for inputs and textareas which might be visually hidden behind custom UI
            const tagName = node.tagName.toLowerCase();
            const isInputLike = tagName === 'input' || tagName === 'textarea' || tagName === 'select' || node.hasAttribute('contenteditable');
            if (!isVisible && isInputLike && computedStyle.display !== 'none' && computedStyle.visibility !== 'hidden') {
                isVisible = true;
            }

            if (isVisible) {
                // Generate and inject unique ID as string of number
                const uniqueId = String(elementIdCounter++);
                node.setAttribute('data-romy-id', uniqueId);

                // Build standard JSON schema expected by the Backend AI Execution Layer
                let textContent = node.innerText || node.value || node.getAttribute('aria-label') || node.getAttribute('placeholder') || node.title || node.name || node.alt || "";
                if (typeof textContent === 'string') {
                    textContent = textContent.trim();
                } else {
                    textContent = String(textContent).trim();
                }

                // Try to avoid completely empty elements unless they are inputs
                if (!textContent && !isInputLike && tagName !== 'button' && tagName !== 'a') {
                     // Still allow but maybe we can prune purely empty non-semantic divs that slipped through?
                     // If it's a div/span that has pointer cursor but no text/aria/etc and no children, might be clutter.
                     if ((tagName === 'div' || tagName === 'span') && node.childElementCount === 0) {
                         return; // prune
                     }
                }

                elements.push({
                    id: uniqueId,
                    type: node.tagName.toLowerCase(),
                    text: textContent,
                    xpath: getXPath(node),
                    // Optionally calculate center coordinates if needed for fallback
                    bounds: {
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height
                    }
                });
            }
        });

        console.log(`Extracted ${elements.length} visible UI elements.`);
        return elements;
    }
};
