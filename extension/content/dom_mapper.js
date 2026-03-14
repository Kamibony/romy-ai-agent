// Global namespace to export functions to the Content Script
window.RomyDomMapper = {
    extractUIElements: function() {
        console.log("Romy DOM Mapper initialized. Injecting and extracting structural UI array.");
        const elements = [];
        let elementIdCounter = 0;

        // Target specifically the visible components to avoid computing hidden bounds
        if (document.visibilityState !== 'visible') {
            console.log("Document is not visible, skipping DOM mapping.");
            return elements;
        }

        // Broad locator string matching Playwright scanning
        const locators = 'button, a, input, select, textarea, [role="button"], [role="link"], [onclick], .btn, .button, [class*="btn"]';

        function isInteractive(el) {
            if (el.matches(locators)) return true;

            // Check ARIA attributes
            if (el.hasAttribute('aria-label') || el.hasAttribute('role')) {
                const role = el.getAttribute('role');
                if (role === 'button' || role === 'link' || role === 'menuitem' || role === 'tab') {
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
                const classes = className.toLowerCase().split(' ');
                if (classes.some(c => c.includes('btn') || c.includes('button') || c.includes('action') || c.includes('submit'))) {
                    return true;
                }
            }

            // Check computed styles for interactivity
            try {
                const style = window.getComputedStyle(el);
                if (style.cursor === 'pointer' && el.tagName !== 'BODY' && el.tagName !== 'HTML') {
                    return true;
                }
            } catch (e) {
                // Ignore errors reading computed styles
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

        const allNodes = getAllNodes(document);

        allNodes.forEach((node) => {
            const rect = node.getBoundingClientRect();

            // Simplified visibility check
            const computedStyle = window.getComputedStyle(node);
            let isVisible = (
                rect.width > 0 &&
                rect.height > 0 &&
                rect.top >= 0 &&
                rect.left >= 0 &&
                rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
                rect.right <= (window.innerWidth || document.documentElement.clientWidth) &&
                computedStyle.visibility !== 'hidden' &&
                computedStyle.display !== 'none' &&
                computedStyle.opacity !== '0'
            );

            // Relax visibility checks for inputs and textareas which might be visually hidden behind custom UI
            const tagName = node.tagName.toLowerCase();
            const isInputLike = tagName === 'input' || tagName === 'textarea' || node.hasAttribute('contenteditable');
            if (!isVisible && isInputLike && computedStyle.display !== 'none') {
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

                elements.push({
                    id: uniqueId,
                    type: node.tagName.toLowerCase(),
                    text: textContent,
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