// Global namespace to export functions to the Content Script
window.RomyDomMapper = {
    extractUIElements: function() {
        console.log("Romy DOM Mapper initialized. Injecting and extracting structural UI array.");
        const elements = [];
        let elementIdCounter = 0;

        // Broad locator string matching Playwright scanning
        const locators = 'button, a, input, select, textarea, [role="button"], [role="link"], [onclick], .btn, .button, [class*="btn"]';

        // Target specifically the visible components to avoid computing hidden bounds
        const allNodes = document.querySelectorAll(locators);

        allNodes.forEach((node) => {
            const rect = node.getBoundingClientRect();

            // Simplified visibility check
            const isVisible = (
                rect.width > 0 &&
                rect.height > 0 &&
                rect.top >= 0 &&
                rect.left >= 0 &&
                rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
                rect.right <= (window.innerWidth || document.documentElement.clientWidth) &&
                window.getComputedStyle(node).visibility !== 'hidden'
            );

            if (isVisible) {
                // Generate and inject unique ID
                const uniqueId = `romy_${elementIdCounter++}`;
                node.setAttribute('data-romy-id', uniqueId);

                // Build standard JSON schema expected by the Backend AI Execution Layer
                let textContent = node.innerText || node.value || node.getAttribute('aria-label') || "";
                textContent = textContent.trim();

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