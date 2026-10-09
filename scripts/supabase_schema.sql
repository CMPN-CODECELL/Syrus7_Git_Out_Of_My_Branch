-- Create the watchlists table
CREATE TABLE watchlists (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id UUID REFERENCES auth.users(id) NOT NULL,
    symbol TEXT NOT NULL,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, symbol) -- Prevent duplicate symbols for the same user
);

-- Enable Row Level Security (RLS)
ALTER TABLE watchlists ENABLE ROW LEVEL SECURITY;

-- Create policy so users can only SELECT their own watchlists
CREATE POLICY "Users can view their own watchlist"
ON watchlists FOR SELECT
USING (auth.uid() = user_id);

-- Create policy so users can only INSERT into their own watchlists
CREATE POLICY "Users can insert into their own watchlist"
ON watchlists FOR INSERT
WITH CHECK (auth.uid() = user_id);

-- Create policy so users can only DELETE from their own watchlists
CREATE POLICY "Users can delete from their own watchlist"
ON watchlists FOR DELETE
USING (auth.uid() = user_id);

-- Create public.users table for profile data
CREATE TABLE public.users (
    id UUID REFERENCES auth.users(id) PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT,
    avatar_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable RLS on users table
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

-- Users can read their own profile
CREATE POLICY "Users can view own profile" 
ON public.users FOR SELECT 
USING (auth.uid() = id);

-- Users can update their own profile
CREATE POLICY "Users can update own profile" 
ON public.users FOR UPDATE 
USING (auth.uid() = id);

-- Function to handle new user signup
CREATE OR REPLACE FUNCTION public.handle_new_user() 
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.users (id, email, full_name, avatar_url)
    VALUES (
        new.id, 
        new.email, 
        new.raw_user_meta_data->>'full_name',
        new.raw_user_meta_data->>'avatar_url'
    );
    RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger to call function on signup
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE PROCEDURE public.handle_new_user();
