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

        let allNodes = getAllNodes(document);

        // De-noising: remove nodes that are just large wrappers (e.g. > 50% of viewport)
        // unless they are explicitly semantic like <button>, <a>, <input>
        const viewportWidth = window.innerWidth || document.documentElement.clientWidth;
        const viewportHeight = window.innerHeight || document.documentElement.clientHeight;

        allNodes = allNodes.filter(node => {
            const rect = node.getBoundingClientRect();
            const isSemantic = node.matches('button, a, input, select, textarea, [role="button"], [role="link"]');

            // If it's just a generic container marked interactive via CSS (cursor: pointer)
            // and it takes up more than 50% of the screen, we probably don't want it.
            if (!isSemantic && (rect.width > viewportWidth * 0.5 || rect.height > viewportHeight * 0.5)) {
                return false;
            }
            return true;
        });

        // De-noising: Deduplicate nested overlaps (keep logical parent, discard fully contained children)
        // If an element is fully contained inside another interactive element, and they have the same center
        // or just broadly overlap, it often creates duplicate targets.
        // A common heuristic: if a child is inside a parent and both are interactive, keep the parent
        // if they essentially cover the same area, or just filter out children of interactive parents
        // if they don't add semantic value. Or filter out the parent if the child is the real target.
        // Actually, usually the outermost interactive element (e.g., <button> or <a>) is the logical parent,
        // and its inner spans/svgs should be ignored.
        const nodesToKeep = new Set(allNodes);

        for (const node of allNodes) {
            let parent = node.parentElement;
            let isContainedInInteractiveParent = false;
            while (parent) {
                if (nodesToKeep.has(parent)) {
                    isContainedInInteractiveParent = true;
                    break;
                }
                parent = parent.parentElement;
            }

            if (isContainedInInteractiveParent) {
                // To be safe, we only discard the child if it's not a distinctly separate interactive element
                // like an input inside a form. <button> > <span> -> remove span.
                // <a> > <img> -> remove img.
                const isDistinct = node.matches('input, select, textarea, button, a');
                const parentIsDistinct = parent && parent.matches('button, a');

                // If parent is a button/link, almost everything inside it is just part of that button/link.
                if (parentIsDistinct && !isDistinct) {
                    nodesToKeep.delete(node);
                } else if (!isDistinct) {
                    // Even if parent is just a 'cursor: pointer' div, if child is also non-distinct, remove child.
                    nodesToKeep.delete(node);
                }
            }
        }

        allNodes = Array.from(nodesToKeep);

        allNodes.forEach((node) => {
            const rect = node.getBoundingClientRect();

            // Simplified visibility check
            const computedStyle = window.getComputedStyle(node);

            // Allow elements that are partially visible / slightly out of viewport bounds
            let isVisible = (
                rect.width > 0 &&
                rect.height > 0 &&
                rect.bottom > 0 && // Element's bottom edge is below top of viewport
                rect.top < (window.innerHeight || document.documentElement.clientHeight) && // Top edge is above bottom of viewport
                rect.right > 0 && // Right edge is past left side
                rect.left < (window.innerWidth || document.documentElement.clientWidth) && // Left edge is before right side
                computedStyle.visibility !== 'hidden' &&
                computedStyle.display !== 'none' &&
                computedStyle.opacity !== '0'
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

                const centerX = rect.x + (rect.width / 2);
                const centerY = rect.y + (rect.height / 2);

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
                    },
                    center: {
                        x: centerX,
                        y: centerY
                    }
                });
            }
        });

        console.log(`Extracted ${elements.length} visible UI elements.`);
        return elements;
    }
};