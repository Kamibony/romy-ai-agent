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

            // Performance: Only check computed style for cursor if it's explicitly one of the structural tags
            // that might be interactive, rather than thousands of spans and divs, unless it has an onclick handler.
            if (el.hasAttribute('onclick') || ['div', 'span', 'li'].includes(el.tagName.toLowerCase())) {
                try {
                    const style = window.getComputedStyle(el);
                    if (style.cursor === 'pointer') {
                        return true;
                    }
                } catch (e) {
                    // Ignore errors reading computed styles
                }
            }

            return false;
        }

        function isInformationNode(el) {
            const tagName = el.tagName.toLowerCase();
            // Data dense nodes: Paragraphs, spans with text, headings, table cells
            if (['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'td', 'th', 'li', 'dd', 'dt'].includes(tagName)) {
                return el.innerText.trim().length > 0;
            }
            // Allow generic spans/divs or custom structural elements if they hold text
            // Remove domain-specific (e.g., fin-streamer) logic to remain universal
            if (tagName === 'span' || tagName === 'div' || el.tagName.includes('-')) {
                // If it's a generic container or custom element, map it if it contains pure text
                // and has a non-trivial amount of text
                if (el.children.length === 0 && el.innerText.trim().length > 0) {
                    return true;
                }
            }
            return false;
        }

        function getAllNodes(root) {
            let nodes = [];
            // Reverting the destructive querySelectorAll optimization because many SPAs use
            // <div> or <span> as clickable elements and we shouldn't filter them early here.
            // We'll rely on the spatial filtering before getComputedStyle as our main optimization.
            const elements = root.querySelectorAll('*');
            elements.forEach(el => {
                // Hierarchical Semantic Weighting: capture both interactive UI and static Information Nodes
                if (isInteractive(el) || isInformationNode(el)) {
                    nodes.push(el);
                }
                if (el.shadowRoot) {
                    nodes = nodes.concat(getAllNodes(el.shadowRoot));
                }
            });
            return nodes;
        }

        function isSemanticId(id) {
            if (!id) return false;
            // E.g. avoid things like 'svelte-1234abcd', 'css-k29d1', 'mui-p-123992', or pure UUIDs
            if (id.length > 20) return false; // Too long, likely auto-generated
            if (/\d{4,}/.test(id)) return false; // Contains 4+ digits
            if (/[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}/i.test(id)) return false; // UUID
            return true;
        }

        function getXPath(element) {
            if (!element) return '';
            const id = element.getAttribute ? element.getAttribute('id') : null;
            if (id && isSemanticId(id)) {
                return 'id("' + id + '")';
            }

            // Prioritize semantic attributes
            if (element.hasAttribute('aria-label')) {
                return `//${element.tagName.toLowerCase()}[@aria-label="${element.getAttribute('aria-label')}"]`;
            }
            if (element.hasAttribute('data-testid')) {
                return `//${element.tagName.toLowerCase()}[@data-testid="${element.getAttribute('data-testid')}"]`;
            }
            if (element.hasAttribute('role')) {
                const text = element.innerText || element.value || '';
                if (text && text.length < 50) {
                     return `//${element.tagName.toLowerCase()}[@role="${element.getAttribute('role')}" and contains(text(), "${text.trim()}")]`;
                }
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

        function isSemanticClass(cls) {
            if (!cls) return false;
            // Ignore tailwind / CSS-in-JS hashes
            if (/\d{3,}/.test(cls)) return false;
            if (/[a-zA-Z0-9]{8,}/.test(cls) && !/^[a-zA-Z]+$/.test(cls)) return false; // Long alphanumeric usually hash
            if (cls.includes(':') || cls.includes('[')) return false; // Tailwind arbitrary
            return true;
        }

        function getCssSelector(el) {
            if (!el) return '';
            if (el.tagName.toLowerCase() == 'html') return 'HTML';

            // Prioritize semantic attributes for CSS selector too
            if (el.hasAttribute('data-testid')) {
                return `${el.tagName.toLowerCase()}[data-testid="${el.getAttribute('data-testid')}"]`;
            }
            if (el.hasAttribute('aria-label')) {
                return `${el.tagName.toLowerCase()}[aria-label="${el.getAttribute('aria-label')}"]`;
            }

            let str = el.tagName.toLowerCase();
            if (el.id && isSemanticId(el.id)) {
                str += '#' + el.id;
            }

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
                        if (!isSemanticClass(classesArr[i])) continue;
                        str += '.' + classesArr[i];
                    }
                }
            }
            return str;
        }

        let allNodes = getAllNodes(document);

        // Define a strong semantic distinctness helper to protect ARIA roles and important tags
        function isDistinctSemanticElement(node) {
            if (node.matches('input, select, textarea, button, a, [role="button"], [role="link"], [role="menuitem"], [role="tab"]')) {
                return true;
            }
            if (node.hasAttribute('aria-label')) {
                return true;
            }
            if (node.tagName.toLowerCase() === 'svg') {
                return true;
            }
            const className = typeof node.className === 'string' ? node.className : (node.className && node.className.baseVal ? node.className.baseVal : '');
            if (className) {
                const classes = className.toLowerCase().split(' ');
                if (classes.some(c => c.includes('btn') || c.includes('button') || c.includes('action') || c.includes('submit'))) {
                    return true;
                }
            }
            return false;
        }

        const viewportWidth = window.innerWidth || document.documentElement.clientWidth;
        const viewportHeight = window.innerHeight || document.documentElement.clientHeight;

        // De-noising: remove nodes that are just large wrappers (e.g. > 50% of viewport)
        // unless they are explicitly semantic
        allNodes = allNodes.filter(node => {
            const rect = node.getBoundingClientRect();
            const isSemantic = isDistinctSemanticElement(node) || isInformationNode(node);

            // If it's just a generic container marked interactive via CSS (cursor: pointer)
            // and it takes up more than 50% of the screen, we probably don't want it.
            if (!isSemantic && (rect.width > viewportWidth * 0.5 || rect.height > viewportHeight * 0.5)) {
                return false;
            }
            return true;
        });

        // Phase 1: Visibility Check
        // We do this BEFORE deduplication to avoid the "0x0 Wrapper Trap".
        // If a parent wrapper is 0x0, it is invisible and discarded here,
        // leaving its visible children intact.
        const visibleNodes = [];

        allNodes.forEach((node) => {
            const rect = node.getBoundingClientRect();

            // Optimization: Fast spatial filter before triggering getComputedStyle
            let isVisible = (
                rect.width > 0 &&
                rect.height > 0 &&
                rect.bottom > 0 && // Element's bottom edge is below top of viewport
                rect.top < (window.innerHeight || document.documentElement.clientHeight) && // Top edge is above bottom of viewport
                rect.right > 0 && // Right edge is past left side
                rect.left < (window.innerWidth || document.documentElement.clientWidth) // Left edge is before right side
            );

            let computedStyle = null;
            if (isVisible) {
                // Only compute style if it passed the spatial bounds check
                try {
                    computedStyle = window.getComputedStyle(node) || {};
                } catch(e) {
                    console.warn("Romy DOM Mapper: Failed to get computed style", e);
                    computedStyle = {};
                }
                isVisible = (
                    computedStyle.visibility !== 'hidden' &&
                    computedStyle.display !== 'none' &&
                    computedStyle.opacity !== '0'
                );
            }

            // Relax visibility checks for inputs and textareas which might be visually hidden behind custom UI
            const tagName = node.tagName.toLowerCase();
            const isInputLike = tagName === 'input' || tagName === 'textarea' || tagName === 'select' || node.hasAttribute('contenteditable');
            if (!isVisible && isInputLike) {
                if (!computedStyle) {
                    try {
                        computedStyle = window.getComputedStyle(node) || {};
                    } catch(e) {
                        computedStyle = {};
                    }
                }
                if (computedStyle.display !== 'none' && computedStyle.visibility !== 'hidden') {
                    isVisible = true;
                }
            }

            if (isVisible) {
                // Perform layout-dependent reads in this phase
                let innerText = node.innerText || "";
                const tag = node.tagName.toLowerCase();
                if ((tag === 'input' || tag === 'textarea' || tag === 'select') && node.value) {
                    // For inputs, value is the primary source of truth for typed text
                    if (innerText && innerText !== node.value) {
                        innerText = innerText + " " + node.value;
                    } else {
                        innerText = node.value;
                    }
                } else if (!innerText && node.value) {
                    innerText = node.value;
                }
                visibleNodes.push({ node, rect, innerText });
            }
        });

        // Phase 2: Structural/Spatial Deduplication on Visible Nodes
        // We use a Set to safely manage which nodes to keep, checking ancestry against visible items only.
        const nodesToKeep = new Set(visibleNodes);
        const visibleNodesMap = new Map();
        visibleNodes.forEach(item => visibleNodesMap.set(item.node, item));

        for (const item of visibleNodes) {
            const node = item.node;
            let parent = node.parentElement;
            let visibleParentItem = null;

            while (parent) {
                if (visibleNodesMap.has(parent)) {
                    visibleParentItem = visibleNodesMap.get(parent);
                    break;
                }
                parent = parent.parentElement;
            }

            if (visibleParentItem && nodesToKeep.has(item) && nodesToKeep.has(visibleParentItem)) {
                const isDistinctChild = isDistinctSemanticElement(node);
                const parentIsDistinct = isDistinctSemanticElement(visibleParentItem.node);

                if (isDistinctChild) {
                    if (!parentIsDistinct) {
                        // Child is distinct (e.g. button), parent is generic (e.g. div with pointer).
                        // Drop the generic parent.
                        nodesToKeep.delete(visibleParentItem);
                    } else {
                        // Both are distinct. e.g. SVG inside a Button.
                        if (node.tagName.toLowerCase() === 'svg') {
                            // Drop SVG if it's inside another distinct interactive parent
                            nodesToKeep.delete(item);
                        }
                    }
                } else {
                    // Child is generic (e.g. span), parent is visible interactive (generic or distinct).
                    // Drop the generic child, the parent represents the interactive region.
                    nodesToKeep.delete(item);
                }
            }
        }

        const finalVisibleNodes = Array.from(nodesToKeep);

        // Write Phase: assign attributes and collect structured data
        finalVisibleNodes.forEach(({ node, rect, innerText }) => {
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

            let textContent = innerText;

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
        });


        // Systemic fix for Fatal Payload Bloat (Issue 1)
        // Sort elements from top-left to bottom-right to prioritize visible elements
        elements.sort((a, b) => {
            if (a.bounds.y !== b.bounds.y) {
                return a.bounds.y - b.bounds.y;
            }
            return a.bounds.x - b.bounds.x;
        });

        console.log(`Extracted ${elements.length} visible UI elements.`);
        return elements;

    }
};