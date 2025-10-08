# --- 1. Configuration, Imports, and Cosmological Constants ---
import pandas as pd
import numpy as np
import warnings
import time
from astropy.cosmology import Planck18 as cosmo
from astropy import units as u
# We need to import the core functions from SageMath and pari directly
# Note: For this script to run, a Python environment with SageMath/pari is required.
try:
    from sage.all import EllipticCurve, QQ, N
except ImportError:
    print("WARNING: SageMath not found. Elliptic curve calculations will fail.")
    EllipticCurve = lambda *args: None
    QQ = N = lambda x: np.nan

import matplotlib.pyplot as plt
from matplotlib import animation
from mpl_toolkits.mplot3d import Axes3D
from scipy.optimize import curve_fit
from datetime import datetime

warnings.filterwarnings("ignore", category=UserWarning)

# --- CONFIGURATION (UPDATE THIS SECTION) ---
INPUT_FILE = 'GalSpecExtra.csv'  # <--- SET YOUR REAL CSV FILENAME HERE
REQUIRED_COLS = ['ra', 'dec', 'z', 'logmass'] # Expected columns in your file
PLOT_PREFIX = 'ucf_full_data_manifold_viz'
CHUNK_SIZE = 50000  # Process this many rows at a time to manage memory/SageMath overhead
MAX_PLOT_POINTS = 100000 # Limit for visualization to maintain responsiveness
# -------------------------------------------

# UCF Cosmological Constants (from Document 10/16)
T_COSMO = 17.18
R_COSMO = 2.51
KAPPA = 1.0

# --- 2. UCF Mapping Functions ---

def derive_curve_coefficients(r_comoving, rho_topological):
    """
    Simulates the UCF's non-linear mapping function: (r, rho) -> (a, b).
    r_comoving is the physical distance, rho_topological is the density proxy (logmass).
    """
    # Scaling laws based on research insights (Documents 13/14)
    # The 'a' coefficient is complex, non-linear function of distance (r)
    a_coeff = -100 * np.log1p(r_comoving) * (r_comoving / 50.0) - 1000
    
    # The 'b' coefficient is linked to density (rho), aiming for arithmetically special curves
    # rho_topological is logmass (e.g., ~10-12), so we must scale it up significantly
    scaled_rho = np.exp(rho_topological) / 1e10  # Scale to a reasonable number theory domain
    b_coeff = 0.5 * scaled_rho + 5000 * np.sin(scaled_rho / 1000) + 100
    
    # Cast to integer for the elliptic curve definition
    return int(a_coeff), int(b_coeff)

def calculate_ucf_invariants(a, b):
    """Calculates the j-invariant for topological density."""
    try:
        # Define Elliptic Curve E: y^2 = x^3 + a*x + b
        E = EllipticCurve(QQ, [0, 0, 0, a, b])
        j_val = N(E.j_invariant())
        
        # We use the log magnitude of the j-invariant as the topological height/density
        log_j_density = np.log1p(np.abs(j_val)) 
        
        return j_val, log_j_density
    except Exception:
        # Represents the "Zone of Intractability" (Document 15)
        return np.nan, np.nan

# --- 3. Chunking and Core Processing Logic ---

def process_chunk(chunk_df, chunk_index):
    """Calculates comoving distance and applies UCF mapping to a single data chunk."""
    
    start_time = time.time()
    
    # 1. Basic Cleaning and Column Check (Done per chunk for safety)
    missing_cols = [col for col in REQUIRED_COLS if col not in chunk_df.columns]
    if missing_cols:
        print(f"Error in Chunk {chunk_index}: Missing required columns: {missing_cols}. Skipping chunk.")
        return pd.DataFrame()
        
    df = chunk_df[REQUIRED_COLS].copy().dropna()
    
    # 2. Calculate Comoving Distance (r) from Redshift (z) using Planck18
    # Exclude objects at z=0 or invalid z
    valid_z = (df['z'] > 0)
    df_valid_z = df[valid_z].copy()
    
    # Astropy calculates distance, then convert to numerical value in Mpc
    df_valid_z['r_comoving'] = cosmo.comoving_distance(df_valid_z['z']).to(u.Mpc).value
    
    # 3. Rename logmass to our theoretical topological density proxy (rho_topological)
    df_valid_z.rename(columns={'logmass': 'rho_topological'}, inplace=True)
    
    # 4. Apply the derivation and calculation row-wise (The slow step)
    results = df_valid_z.apply(
        lambda row: calculate_ucf_invariants(
            *derive_curve_coefficients(row['r_comoving'], row['rho_topological'])
        ),
        axis=1, result_type='expand'
    )
    
    results.columns = ['j_invariant', 'log_j_density']
    df_processed = pd.concat([df_valid_z, results], axis=1)
    
    # Filter out intractable curves
    valid_rows = df_processed['log_j_density'].notna()
    df_final = df_processed[valid_rows].copy()
    
    end_time = time.time()
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Chunk {chunk_index}: Processed {len(chunk_df)} rows, {len(df_final)} tractable curves. Time: {end_time - start_time:.2f}s")
    
    return df_final

def process_full_dataset(filepath):
    """Reads the entire CSV in chunks and processes them sequentially."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] STEP 1: Starting Chunked Data Processing from {filepath} (Chunk Size: {CHUNK_SIZE})...")
    
    try:
        reader = pd.read_csv(filepath, chunksize=CHUNK_SIZE)
    except FileNotFoundError:
        print(f"Error: File not found at {filepath}. Please update INPUT_FILE.")
        return pd.DataFrame()

    all_results = []
    total_processed = 0
    
    for i, chunk in enumerate(reader):
        total_processed += len(chunk)
        processed_chunk = process_chunk(chunk, i + 1)
        if not processed_chunk.empty:
            all_results.append(processed_chunk)
            
    if not all_results:
        print("No data processed successfully.")
        return pd.DataFrame()
        
    df_combined = pd.concat(all_results, ignore_index=True)
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] STEP 2: Full Processing Complete. Total rows processed: {total_processed}. Total tractable curves: {len(df_combined)}.")
    
    return df_combined

# --- 4. Visualization Functions (Adjusted for Sampling) ---

def visualize_manifold(df):
    """Generates 3D visualizations of the topological manifold, sampling if needed."""
    
    df_plot = df.copy()
    if len(df_plot) > MAX_PLOT_POINTS:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Sampling data down to {MAX_PLOT_POINTS} points for fast visualization.")
        df_plot = df_plot.sample(n=MAX_PLOT_POINTS, random_state=42).copy()
        
    print(f"[{datetime.now().strftime('%H:%M:%S')}] STEP 3: Generating 3D Manifold Visualizations ({len(df_plot)} points)...")

    # Convert RA/DEC/r_comoving to Cartesian (X, Y, Z) for 3D plotting
    X = df_plot['r_comoving'] * np.cos(np.deg2rad(df_plot['ra'])) * np.cos(np.deg2rad(df_plot['dec']))
    Y = df_plot['r_comoving'] * np.sin(np.deg2rad(df_plot['ra'])) * np.cos(np.deg2rad(df_plot['dec']))
    Z = df_plot['r_comoving'] * np.sin(np.deg2rad(df_plot['dec']))
    
    # Use log_j_density as the color/topological density
    C = df_plot['log_j_density']
    
    # --- 4a. Scatter Plot (Topological Density Map) ---
    fig = plt.figure(figsize=(12, 10))
    ax = fig.add_subplot(111, projection='3d')
    scatter = ax.scatter(X, Y, Z, c=C, cmap='viridis', s=50, alpha=0.7)
    
    ax.set_xlabel('Comoving X (Mpc)')
    ax.set_ylabel('Comoving Y (Mpc)')
    ax.set_zlabel('Comoving Z (Mpc)')
    ax.set_title(f'3D Cosmic Web Manifold: Log|j-invariant| Density ($\\rho_{{topo}}$)')
    
    cbar = fig.colorbar(scatter, pad=0.1)
    cbar.set_label('Elliptic Curve Complexity (Log|j-invariant|)')
    
    plt.tight_layout()
    plt.savefig(f'{PLOT_PREFIX}_scatter_density.png')
    plt.close(fig)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Plot saved: {PLOT_PREFIX}_scatter_density.png")
    
    # --- 4b. Manifold Surface Fit (Topographical View) ---
    fig_surface = plt.figure(figsize=(12, 10))
    ax_surface = fig_surface.add_subplot(111, projection='3d')
    
    # Use RA/DEC as the grid coordinates, and log_j_density as the height (Z-axis)
    X_fit = df_plot['ra'].values
    Y_fit = df_plot['dec'].values
    Z_fit = df_plot['log_j_density'].values
    
    def poly2(coords, a, b, c, d, e, f):
        x, y = coords
        return a * x**2 + b * y**2 + c * x * y + d * x + e * y + f

    # Normalize coordinates for stable fitting
    X_norm = (X_fit - X_fit.mean()) / X_fit.std()
    Y_norm = (Y_fit - Y_fit.mean()) / Y_fit.std()
    
    try:
        popt, pcov = curve_fit(poly2, (X_norm, Y_norm), Z_fit)
        
        # Create grid for plotting the fitted surface
        ra_range = np.linspace(X_fit.min(), X_fit.max(), 50)
        dec_range = np.linspace(Y_fit.min(), Y_fit.max(), 50)
        RA_grid, DEC_grid = np.meshgrid(ra_range, dec_range)
        
        RA_grid_norm = (RA_grid - X_fit.mean()) / X_fit.std()
        DEC_grid_norm = (DEC_grid - Y_fit.mean()) / Y_fit.std()
        
        Z_surface = poly2((RA_grid_norm, DEC_grid_norm), *popt)
        
        ax_surface.plot_surface(RA_grid, DEC_grid, Z_surface, cmap='plasma', alpha=0.8, edgecolors='none')
    except RuntimeError:
        print("Warning: Could not fit polynomial surface (not enough points or ill-conditioned data). Plotting scatter only.")
    except ValueError:
        print("Warning: Insufficient data points for surface fit after sampling/filtering.")

    # Scatter the original points underneath
    ax_surface.scatter(X_fit, Y_fit, Z_fit, c=Z_fit, cmap='plasma', s=20, alpha=0.4)
    
    ax_surface.set_xlabel('Right Ascension (deg)')
    ax_surface.set_ylabel('Declination (deg)')
    ax_surface.set_zlabel('Topological Density (Log|j-invariant|)')
    ax_surface.set_title('Topological Density Manifold Surface Fit (UCF)')
    plt.tight_layout()
    plt.savefig(f'{PLOT_PREFIX}_surface_fit.png')
    plt.close(fig_surface)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Plot saved: {PLOT_PREFIX}_surface_fit.png")

    return X, Y, Z, C 

# --- 5. Animation Function (Building the Manifold) ---

def animate_manifold(X, Y, Z, C):
    """Creates an animation showing the 3D scatter plot accumulating points."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] STEP 4: Creating Manifold Animation (MP4)...")
    
    # Use a fraction of points for faster animation
    N_FRAMES = 100
    df_anim = pd.DataFrame({'X': X, 'Y': Y, 'Z': Z, 'C': C})
    
    # Ensure there are enough points for the animation frames
    if len(df_anim) < N_FRAMES:
        N_FRAMES = len(df_anim)

    # Sample the data points across the total range for the animation steps
    df_anim = df_anim.iloc[::max(1, len(X) // N_FRAMES)].reset_index(drop=True)
    
    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection='3d')
    ax.set_title('UCF: Manifold Formation (Comoving Coordinates)')
    ax.set_xlabel('Comoving X')
    ax.set_ylabel('Comoving Y')
    ax.set_zlabel('Comoving Z')
    
    points = ax.scatter([], [], [], c=[], cmap='viridis', s=20, alpha=0.8)

    ax.set_xlim(X.min(), X.max())
    ax.set_ylim(Y.min(), Y.max())
    ax.set_zlim(Z.min(), Z.max())

    # Set up color bar based on max/min density
    min_c, max_c = C.min(), C.max()
    points.set_clim(min_c, max_c)
    fig.colorbar(points, ax=ax, shrink=0.5, aspect=5).set_label('Log|j-invariant|')

    def update(frame):
        """Update function for the animation."""
        idx = frame + 1
        X_data = df_anim['X'].iloc[:idx]
        Y_data = df_anim['Y'].iloc[:idx]
        Z_data = df_anim['Z'].iloc[:idx]
        C_data = df_anim['C'].iloc[:idx]
        
        points._offsets3d = (X_data, Y_data, Z_data)
        points.set_array(C_data)
        
        # Optionally update view angle
        ax.view_init(elev=30, azim=frame * 0.5)
        
        return points,

    # Create the animation
    ani = animation.FuncAnimation(
        fig, update, frames=len(df_anim), interval=100, blit=False, repeat=False
    )

    # Attempt to save the animation (requires FFmpeg)
    try:
        filepath = f'{PLOT_PREFIX}_manifold_build.mp4'
        ani.save(filepath, writer='ffmpeg', fps=10, dpi=100)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Animation saved: {filepath}")
    except ValueError as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] WARNING: Failed to save MP4 animation (FFmpeg issue or not found).")
    
    plt.close(fig)

# --- 6. Execution Block ---

if __name__ == '__main__':
    
    print("--- Starting UCF Topological Manifold Pipeline (FULL DATA/CHUNKED MODE) ---")
    
    # 1. Process Data in Chunks
    df_processed = process_full_dataset(INPUT_FILE)
    
    if df_processed.empty:
        print("Pipeline Halted: Data processing failed or no tractable curves found.")
    else:
        # 2. Visualize Manifold (Sampling if necessary)
        X, Y, Z, C = visualize_manifold(df_processed)
        
        # 3. Animate Manifold Construction
        animate_manifold(X, Y, Z, C)
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Pipeline Complete. Check files starting with '{PLOT_PREFIX}_' for output.")
