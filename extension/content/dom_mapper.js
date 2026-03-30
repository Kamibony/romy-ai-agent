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

        function getAncestryContext(el) {
            const path = [];
            let current = el.parentElement;
            let depth = 0;
            const maxDepth = 5;

            while (current && current.tagName !== 'BODY' && current.tagName !== 'HTML' && depth < maxDepth) {
                const tagName = current.tagName.toLowerCase();

                // Prioritize explicit structural and testing identifiers
                const id = current.id ? `#${current.id}` : '';
                const testId = current.getAttribute('data-testid') ? `[data-testid="${current.getAttribute('data-testid')}"]` : '';
                const role = current.getAttribute('role') ? `[role="${current.getAttribute('role')}"]` : '';

                // Add common structural semantic tags
                const isSemantic = ['nav', 'header', 'footer', 'main', 'aside', 'section', 'article', 'form', 'ul', 'li', 'dialog'].includes(tagName);

                if (id || testId || role || isSemantic) {
                    let descriptor = tagName;
                    if (id) descriptor += id;
                    if (testId) descriptor += testId;
                    if (!id && !testId && role) descriptor += role;

                    path.unshift(descriptor);
                    depth++;
                }

                current = current.parentElement;
            }

            return path.join(' > ');
        }

        function getCssSelector(el) {
            if (!el) return '';
            if (el.tagName.toLowerCase() == 'html') return 'HTML';
            let str = el.tagName;
            str += (el.id != '') ? '#' + el.id : '';
            if (el.className) {
                let classes = '';
                if (typeof el.className === 'string') {
                    classes = el.className;
                } else if (el.className && el.className.baseVal) {
                    classes = el.className.baseVal;
                }
                if (classes) {
                    let classesArr = classes.split(/\s+/).filter(Boolean);
                    for (let i = 0; i < classesArr.length; i++) {
                        // avoid dynamically generated classes if possible
                        if (!classesArr[i].match(/^[a-zA-Z0-9-_]+$/)) continue;
                        str += '.' + classesArr[i];
                    }
                }
            }
            return str;
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
            let interactiveParent = null;
            while (parent) {
                if (nodesToKeep.has(parent)) {
                    interactiveParent = parent;
                    break;
                }
                parent = parent.parentElement;
            }

            if (interactiveParent) {
                const isDistinctChild = node.matches('input, select, textarea, button, a');
                const parentIsDistinct = interactiveParent.matches('button, a');

                if (isDistinctChild) {
                    // If the child is distinctly interactive (like input or button), we definitely want to keep it.
                    // But if it's inside a generic interactive wrapper (like a form or a large div),
                    // we should probably discard the generic wrapper so we don't end up with overlapping targets.
                    if (!parentIsDistinct) {
                        nodesToKeep.delete(interactiveParent);
                    }
                } else {
                    // If the child is not distinctly interactive (e.g., a span or svg),
                    // and it's inside an interactive parent, we don't need the child as a separate target.
                    nodesToKeep.delete(node);
                }
            }
        }

        allNodes = Array.from(nodesToKeep);

        allNodes.forEach((node) => {
            const rect = node.getBoundingClientRect();

            const computedStyle = window.getComputedStyle(node);

            // Viewport Pruning: Algorithmic reduction to strictly include only elements intersecting the visible viewport
            const viewportWidth = window.innerWidth || document.documentElement.clientWidth;
            const viewportHeight = window.innerHeight || document.documentElement.clientHeight;

            let isVisible = (
                rect.width > 0 &&
                rect.height > 0 &&
                rect.bottom >= 0 && // Element's bottom edge is inside or on top of viewport
                rect.top <= viewportHeight && // Top edge is inside or on bottom of viewport
                rect.right >= 0 && // Right edge is inside or on left side
                rect.left <= viewportWidth && // Left edge is inside or on right side
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

                // Aggressive A11y Extraction for Icon-Only Target Blindness
                let a11yLabel = node.getAttribute('aria-label') || node.getAttribute('title') || node.getAttribute('alt') || node.name || node.getAttribute('placeholder') || "";

                // If it's an SVG or contains an SVG, try to extract the <title> tag
                if (!a11yLabel && (node.tagName.toLowerCase() === 'svg' || node.querySelector('svg'))) {
                    const svgNode = node.tagName.toLowerCase() === 'svg' ? node : node.querySelector('svg');
                    const titleNode = svgNode.querySelector('title');
                    if (titleNode) {
                        a11yLabel = titleNode.textContent;
                    }
                }

                // If aria-labelledby is present, try to find the linked element's text
                if (!a11yLabel && node.hasAttribute('aria-labelledby')) {
                    const labelledBy = node.getAttribute('aria-labelledby');
                    const labelElement = document.getElementById(labelledBy);
                    if (labelElement) {
                        a11yLabel = labelElement.textContent;
                    }
                }

                let textContent = node.innerText || node.value || "";

                if (typeof textContent === 'string') {
                    textContent = textContent.trim();
                } else {
                    textContent = String(textContent).trim();
                }

                if (typeof a11yLabel === 'string') {
                    a11yLabel = a11yLabel.trim();
                } else {
                    a11yLabel = String(a11yLabel).trim();
                }

                if (a11yLabel && a11yLabel !== textContent) {
                    textContent = `[A11y: ${a11yLabel}] ${textContent}`.trim();
                } else if (!textContent && a11yLabel) {
                    textContent = `[A11y: ${a11yLabel}]`;
                }

                const centerX = rect.x + (rect.width / 2);
                const centerY = rect.y + (rect.height / 2);

                elements.push({
                    id: uniqueId,
                    type: node.tagName.toLowerCase(),
                    text: textContent,
                    xpath: getXPath(node),
                    css_selector: getCssSelector(node),
                    ancestry: getAncestryContext(node),
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


        console.log(`Extracted ${elements.length} visible UI elements using strict Viewport Pruning.`);
        return elements;

    }
};