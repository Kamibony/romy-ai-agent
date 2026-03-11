const CONTENT_MESSAGE_TYPES = {
    // Popup -> Background
    PROCESS_COMMAND: 'PROCESS_COMMAND',

    // Background -> Content Script
    REQUEST_DOM_MAP: 'REQUEST_DOM_MAP',
    EXECUTE_ACTION: 'EXECUTE_ACTION',

    // Auth related
    UPDATE_TOKEN: 'UPDATE_TOKEN',
    GET_TOKEN: 'GET_TOKEN',

    // Future (Phase 2): Background -> Native Host
    OS_NATIVE_ACTION: 'OS_NATIVE_ACTION'
};

// Available globally in the content script context
window.MESSAGE_TYPES = CONTENT_MESSAGE_TYPES;