// Global namespace to export functions to the Content Script
window.RomyDomMapper = {
    extractUIElements: function() {
        console.log("Romy DOM Mapper initialized. Returning minimal structural UI array for Vision-First architecture.");
        // We have stripped out the heavy DOM pruning logic since we are relying on vision
        return [];
    }
};
