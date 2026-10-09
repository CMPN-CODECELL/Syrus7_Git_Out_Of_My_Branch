let supabaseClient = null;

async function initSupabase() {
    if (supabaseClient) return supabaseClient;

    try {
        const response = await fetch('/config');
        const config = await response.json();

        if (!config.supabaseUrl || !config.supabaseKey) {
            console.error('Supabase URL or Key is missing from config');
            return null;
        }

        supabaseClient = supabase.createClient(config.supabaseUrl, config.supabaseKey);
        window.supabaseClient = supabaseClient;
        return supabaseClient;
    } catch (error) {
        console.error('Failed to initialize Supabase:', error);
        return null;
    }
}

// Automatically initialize when loaded
initSupabase();
