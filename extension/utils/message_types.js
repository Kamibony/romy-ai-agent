// MESSAGE_TYPES for background script
const MESSAGE_TYPES = {
    // Popup -> Background
    PROCESS_COMMAND: 'PROCESS_COMMAND',

    // Background -> Content Script
    REQUEST_DOM_MAP: 'REQUEST_DOM_MAP',
    EXECUTE_ACTION: 'EXECUTE_ACTION',

    // Auth related
    UPDATE_TOKEN: 'UPDATE_TOKEN',
    GET_TOKEN: 'GET_TOKEN',

    // Offscreen audio capture
    START_RECORDING: 'START_RECORDING',
    STOP_RECORDING: 'STOP_RECORDING',

    // Future (Phase 2): Background -> Native Host
    OS_NATIVE_ACTION: 'OS_NATIVE_ACTION'
};

export { MESSAGE_TYPES };