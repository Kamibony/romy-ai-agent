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
        const locators = 'button, a, input, select, textarea, [role="button"], [role="link"], [role="menuitem"], [role="tab"], [role="checkbox"], [role="radio"], [role="switch"], [role="combobox"], [role="textbox"], [role="searchbox"], [role="widget"], [role="slider"], [role="spinbutton"], [role="listbox"], [role="option"], [role="gridcell"], [role="treeitem"], [onclick], [tabindex]:not([tabindex="-1"]), [contenteditable]:not([contenteditable="false"])';

        function isInteractive(el) {
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
                const classes = className.toLowerCase().split(/\s+/);
                // Require exact matches or strict prefixes/suffixes to prevent vacuuming structural wrappers (e.g., 'action-bar', 'submit-container')
                if (classes.some(c => c === 'btn' || c === 'button' || c.endsWith('-btn') || c.endsWith('-button') || c.startsWith('btn-') || c === 'submit' || c.includes('datepicker') || c.endsWith('-input') || c.includes('dropdown') || c.includes('suggestion') || c.includes('modal') || c.includes('popup') || c.includes('menu') || c.includes('autocomplete') || c.includes('select'))) {
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
                rect.bottom >= 0 && // Element's bottom edge is strictly within or below top of viewport
                rect.top <= (window.innerHeight || document.documentElement.clientHeight) && // Top edge is strictly above or within bottom of viewport
                rect.right >= 0 && // Right edge is strictly within or past left side
                rect.left <= (window.innerWidth || document.documentElement.clientWidth) && // Left edge is strictly within or before right side
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

                // Aggressive Pruning: If the element has no meaningful text and isn't an input/button, drop it
                // Make sure to preserve elements with a Set-of-Mark ID or critical semantic containers
                let keepDueToClass = false;
                const classNameStr = typeof node.className === 'string' ? node.className : (node.className && node.className.baseVal ? node.className.baseVal : '');
                if (classNameStr) {
                    const classes = classNameStr.toLowerCase().split(/\s+/);
                    if (classes.some(c => c.includes('dropdown') || c.includes('suggestion') || c.includes('modal') || c.includes('popup') || c.includes('menu') || c.includes('autocomplete') || c.includes('select'))) {
                        keepDueToClass = true;
                    }
                }

                if (!textContent && !isInputLike && tagName !== 'button' && tagName !== 'a' && !node.hasAttribute('data-romy-id') && tagName !== 'form' && tagName !== 'dialog' && !keepDueToClass) {
                     // If it has children, maybe it's a structural wrapper. But we want to flatten.
                     // If it's literally just an empty div/span with no aria, drop it completely.
                     return;
                }

                // If it's just an empty anchor tag without text or aria-label, drop it
                if (tagName === 'a' && !textContent && !node.hasAttribute('data-romy-id') && !node.hasAttribute('aria-label')) {
                    return;
                }

                // If it's an empty button, but not an icon button (no svg children), drop it
                if (tagName === 'button' && !textContent && node.querySelector('svg') === null && !node.hasAttribute('data-romy-id') && !node.hasAttribute('aria-label')) {
                    return;
                }

                elements.push({
                    id: uniqueId,
                    type: node.tagName.toLowerCase(),
                    text: textContent,
                    xpath: getXPath(node),
                    // Only send essential bounds to save payload size
                    bounds: {
                        x: rect.x + window.scrollX,
                        y: rect.y + window.scrollY,
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
