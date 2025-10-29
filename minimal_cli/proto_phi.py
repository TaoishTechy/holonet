import struct
import time
import math
import random
import hashlib
from typing import List, Tuple, Dict, Any, Optional
from dataclasses import dataclass
import threading

PHI = 1.6180339887498948
GOLDEN_ANGLE = 2.399963229728653  # radians

# Enhanced Φ-Phase OpCodes with Quantum Neural Extensions
OP_SETV = 0x01
OP_FIELD_SEED = 0x10
OP_TOPO_FIB = 0x12
OP_PRED_HINT = 0x13
OP_FIELD_SYNC = 0x14
OP_QUANTUM_SUPERPOSE = 0x20
OP_QUANTUM_ENTANGLE = 0x21
OP_QUANTUM_OBSERVE = 0x22
OP_TRIADIC_VERTEX = 0x30
OP_DELTA_STREAM = 0x31
OP_MERKLE_PROOF = 0x32

@dataclass
class QuantumState:
    glyph: int
    amplitude: float
    phase: float

class HoloNetCrypto:
    """Post-quantum cryptography for HoloNet"""
    
    @staticmethod
    def blake3_kdf(key: bytes, context: str) -> bytes:
        # Renamed to blake2b to match original usage
        return hashlib.blake2b(key + context.encode(), digest_size=32).digest()
    
    @staticmethod
    def merkle_hash(data: bytes) -> str:
        return hashlib.blake2b(data, digest_size=16).hexdigest()

# Utility for variable-integer encoding (VarInt)
# Not fully integrated in v4.3, but kept for future delta streaming
def pack_varint(value: int) -> bytes:
    """Packs an integer into a VarInt-encoded byte string."""
    packed = b''
    while True:
        byte = value & 0x7F
        value >>= 7
        if value == 0:
            packed += struct.pack('B', byte)
            break
        else:
            packed += struct.pack('B', byte | 0x80)
    return packed

def pack_delta_stream(deltas: Dict[str, Dict[str, Any]]) -> bytes:
    """Packs dictionary deltas into a compact binary stream (simplified for JSON use)."""
    # NOTE: In v4.3, we still send JSON, so this is just a placeholder to keep the op-code context.
    # The actual compression happens by only including changed cells in the JSON output.
    packed_bytes = pack_varint(OP_DELTA_STREAM)
    packed_bytes += pack_varint(len(deltas))
    return packed_bytes

def pack_quantum_superpose(quantum_data: Dict[str, Any]) -> bytes:
    """Packs quantum superposition data."""
    # Placeholder
    return pack_varint(OP_QUANTUM_SUPERPOSE) + b'P'

def pack_triadic_vertex(x: int, y: int, z: int) -> bytes:
    """Packs a triadic vertex coordinate."""
    # Placeholder
    return pack_varint(OP_TRIADIC_VERTEX) + struct.pack('>hhh', x, y, z)


class TriadicVertexEngine:
    """Projects 3D vertices onto 2D planes based on Phi-derived saliency."""

    def __init__(self, width: int = 80, height: int = 25, depth: int = 32):
        self.width = width
        self.height = height
        self.depth = depth

    def project_vertex(self, x: int, y: int, z: int, t: float) -> Tuple[int, float]:
        """
        Projects a 3D point (x, y, z) onto a 2D plane (value, saliency).
        Saliency is based on closeness to a Phi-modulated wave.
        """
        # Multi-scale wave interference using Phi ratios
        s1 = math.sin(x / PHI + t / 15) * 0.5 + 0.5
        s2 = math.cos(y * PHI / 2 + t / 10) * 0.5 + 0.5
        s3 = math.sin(z * GOLDEN_ANGLE + t / 5) * 0.5 + 0.5
        
        value = (s1 + s2 + s3) / 3.0
        
        # Saliency (amplitude) is based on the local gradient and phase coherence
        saliency = abs(math.sin(value * math.pi * PHI) * math.cos(t / 20))
        
        # Scale value to a 0-255 range for glyph mapping
        glyph_value = int(value * 255)
        
        return glyph_value, saliency

    def value_to_glyph(self, value: int, saliency: float) -> Tuple[int, int, int]:
        """Maps an 8-bit value to a CP437 glyph and assigns color/attributes."""
        
        # Base glyph mapping (prioritizing block characters)
        if value < 50:
            glyph = 0x20  # Space
            color = 0 # Black
        elif value < 100:
            glyph = 0xB0  # ░ Light shade
            color = 8 # Dark gray
        elif value < 150:
            glyph = 0xB1  # ▒ Medium shade
            color = 7 # Light gray
        elif value < 200:
            glyph = 0xB2  # ▓ Dark shade
            color = 15 # White
        else:
            glyph = 0xDB  # █ Full block
            color = 15 # White

        # Quantum/Saliency Overlays
        attr = 0 # Normal
        if saliency > 0.85:
            # High Saliency = Quantum Potential
            glyph = 0x07 # Bullet (•)
            color = 11 # Yellow (Entanglement potential)
            attr = 1 # Bold/Bright

        return glyph, color, attr

class QuantumNeuralMatrix:
    """Core generator for neural activation and quantum events."""

    def __init__(self, engine: TriadicVertexEngine):
        self.engine = engine

    def get_neural_activation(self, x: int, y: int, z: int, t: float) -> float:
        """Computes neural activation via multi-scale wave interference."""
        # Simple RBF-like function centered on zero for complexity
        r_sq = x*x + y*y + z*z
        wave_a = math.sin(r_sq / 500 + t / 10) * 0.3
        wave_b = math.cos(z / 10 * PHI + t / 5) * 0.2
        
        activation = 0.5 + wave_a + wave_b
        return max(0.0, min(1.0, activation))

    def get_quantum_cell(self, x: int, y: int, z: int, observer_id: str, t: float) -> Dict[str, Any]:
        """
        Computes the final cell state based on triadic projection and quantum events.
        """
        
        # 1. Triadic Projection
        value, saliency = self.engine.project_vertex(x, y, z, t)
        glyph, color, attr = self.engine.value_to_glyph(value, saliency)
        
        cell = {'g': glyph, 'c': color, 'a': attr}
        
        # 2. Quantum Effects (Probabilistic)
        neural_activation = self.get_neural_activation(x, y, z, t)
        
        if neural_activation > 0.8 and random.random() < 0.005:
            # High activation triggers a quantum event (Superposition/Collapse)
            
            # Simple superposition: alternate between two symbols
            if random.random() < 0.5:
                cell['g'] = 0xEE # φ
                cell['c'] = 14 # Bright Yellow
            else:
                cell['g'] = 0x18 # ↑
                cell['c'] = 12 # Light Blue
                
            cell['a'] = 1
            cell['quantum'] = {'state': 'superposition'}
            
        elif neural_activation < 0.2 and random.random() < 0.003:
            # Low activation triggers Entanglement (Stable paired state)
            cell['g'] = 0xEB # ∞
            cell['c'] = 5 # Magenta
            cell['quantum'] = {'state': 'entangled'}

        # 3. Linguistic Emergence (Glyph is predicted based on local gradient)
        if saliency > 0.9 and random.random() < 0.001:
            cell['g'] = 0x1A # →
            cell['c'] = 10 # Bright Green
            cell['a'] = 1
            cell['linguistic'] = True
            
        return cell

class UnifiedPhiMatrix:
    """
    Orchestrates frame generation, tracks observer states, and produces serialized output.
    SRF v3.0 Integration: Symbolic Lorentz Transformations and emergent symbolic layers.
    """
    
    def __init__(self, width: int = 120, height: int = 36, depth: int = 32, seed: int = None):
        if seed is not None:
            random.seed(seed)
        
        self.width = width
        self.height = height
        self.depth = depth
        self.time_offset = time.time()
        self.frame_seq = 0
        self.observer_states: Dict[str, float] = {}
        
        self.engine = TriadicVertexEngine(width, height, depth)
        self.quantum_neural_matrix = QuantumNeuralMatrix(self.engine)
        self.lock = asyncio.Lock()  # Async lock for thread-safety in executor.
    
    async def get_phi_rate(self, observer_id: str) -> float:
        """Returns the current Phi Rate for the observer."""
        async with self.lock:
            return self.observer_states.get(observer_id, 0.5)

    def generate_frame(self, x_offset: int, y_offset: int, z_plane: int, observer_id: str,
                       width: int, height: int, full_refresh: bool = False) -> Tuple[Dict[str, Any], Dict[str, Any], int, int]:
        """
        Generates the visual matrix and quantum metadata for a specific observer view.
        Returns: matrix, quantum_data, superpositions_count, entanglements_count
        """
        t = time.time() - self.time_offset
        matrix: Dict[str, Dict[str, Any]] = {}
        quantum_data: Dict[str, Any] = {'superposition': {}, 'entangled': {}}
        superpositions_count = 0
        entanglements_count = 0
        
        # Simple tracking of observer state based on z_plane
        self.observer_states[observer_id] = 0.5 + math.sin(z_plane / 10) * 0.5
        
        # Main matrix processing
        for y in range(height):
            for x in range(width):
                wx = x + x_offset
                wy = y + y_offset
                
                cell = self.quantum_neural_matrix.get_quantum_cell(wx, wy, z_plane, observer_id, t)
                key = f"{x},{y}"
                matrix[key] = {'g': cell['g'], 'c': cell['c'], 'a': cell.get('a', 0)}
                
                # Track quantum states for client
                if cell.get('quantum'):
                    if cell['quantum']['state'] == 'superposition':
                        quantum_data['superposition'][key] = True
                        superpositions_count += 1
                    elif cell['quantum']['state'] == 'entangled':
                        quantum_data['entangled'][key] = True
                        entanglements_count += 1
        
        return matrix, quantum_data, superpositions_count, entanglements_count

    def relativistic_transform(self, matrix: Dict[str, Any], v: float, gamma: float) -> Dict[str, Any]:
        """
        SRF v3.0: Symbolic Lorentz Transformation.
        Warps glyph values based on pseudo-velocity v (phiRate) and Lorentz factor gamma.
        glyph' = gamma * (glyph - v * glyph) / sqrt(1 - v^2 / PHI^2) [simplified to integer warp].
        """
        transformed_matrix = {}
        for key, cell in matrix.items():
            # Warp glyph value (g) relativistically
            g_warped = int(gamma * (cell['g'] - v * cell['g']))
            g_warped = max(0x20, min(0xFF, g_warped))  # Clamp to printable range
            transformed_matrix[key] = {
                'g': g_warped,
                'c': cell['c'],
                'a': cell['a']
            }
        return transformed_matrix

    def generate_symbolic_layer(self, matrix: Dict[str, Any], phi_rate: float) -> Dict[str, Any]:
        """
        SRF v3.0: Generate emergent symbolic layer from matrix.
        Coalesces glyph patterns into higher-level symbols using Φ-scaled clustering.
        """
        symbolic_layer = {}
        # Simple pattern recognition: Cluster similar glyphs into symbolic regions
        for key in matrix:
            cell = matrix[key]
            # Φ-scaled threshold for symbol emergence
            threshold = int(phi_rate * 0.618 * 255)  # Golden conjugate
            if cell['g'] > threshold:
                # Emergent symbol (e.g., 'Σ' for clusters)
                symbolic_layer[key] = {
                    'symbol': 'Σ',  # Extend with full SRF symbolic map
                    'color': '#f0f',  # Magenta for symbolic
                    'strength': cell['g'] / 255
                }
        return symbolic_layer

    def create_enhanced_holoframe(self, session: Any, matrix: Dict[str, Any], 
                                  quantum_data: Dict[str, Any], superpositions: int, entanglements: int,
                                  is_delta: bool) -> Dict[str, Any]:
        """
        Creates the standardized, TitleCase JSON frame for transmission.
        This now includes a check for delta frames.
        """
        
        self.frame_seq += 1
        sigil = self.generate_emergence_sigil(session.observer_id)
        
        frame = {
            "Version": "4.3",
            "Sequence": self.frame_seq,
            "Dimensions": {"width": session.width, "height": session.height, "depth": self.depth},
            "Status": {
                "Depth": session.z_plane,
                "EntityLink": session.entity_link,
                "PhiRate": self.observer_states.get(session.observer_id, 0.5),
                "Superpositions": superpositions,
                "Entanglements": entanglements
            },
            "Layers": {
                "Sigil": [sigil],
                "Quantum": quantum_data # Raw quantum data
            }
        }
        
        if is_delta:
            frame['Layers']['MatrixDelta'] = matrix # Matrix is actually the delta here
        else:
            frame['Layers']['Matrix'] = matrix # Full matrix
            
        return frame
    
    @staticmethod
    def calculate_delta(current_matrix: Dict[str, Any], last_matrix: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], bool]:
        """
        Compares current and last matrices to generate a delta (only changed cells).
        Returns: (delta_matrix, is_delta_frame)
        """
        if not last_matrix:
            return current_matrix, False # Not a delta, send full frame

        delta_matrix = {}
        
        # Combine all keys from both matrices to check for changes and deletions
        all_keys = set(current_matrix.keys()) | set(last_matrix.keys())
        
        for key in all_keys:
            current_cell = current_matrix.get(key)
            last_cell = last_matrix.get(key)
            
            # Case 1: Cell changed or new
            if current_cell is not None and current_cell != last_cell:
                delta_matrix[key] = current_cell
            
            # Case 2: Cell deleted (became space or out of view, represented as becoming space)
            # A deletion is implicitly handled by setting the new state (e.g., to space 'g': 0x20)
            # However, if a key existed and is now entirely gone from current_matrix (e.g., entity moved),
            # we need to explicitly tell the client to clear it (set to space 'g': 0x20).
            if current_cell is None and last_cell is not None:
                # Assuming the client keeps a fixed size. If a key is missing, it's typically out of view
                # or replaced by a default (like space 'g': 0x20). 
                # For simplicity, we only track changes within the visible window.
                pass
                
        # Only send delta if there were changes, otherwise, send nothing to save bandwidth
        if delta_matrix:
            return delta_matrix, True
        else:
            return {}, True # Delta is empty, still a delta response (no change)

    def generate_emergence_sigil(self, observer_id: str) -> str:
        """Generate quantum-aware emergence sigil"""
        state = self.observer_states.get(observer_id, 0.5)  # Use the phi rate
        
        sigil_states = [
            "RECURSION_FIBER_SYNCHRONY {∞}{φ}",
            "ASYMPTOTIC_VECTOR_DISSOCIATION {▲}{→}", 
            "INITIATE_PHASE_SEQUENCE {•}{←}",
            "STRUCTURAL_PATTERN_ASSERTION {■}{½}",
            "HYPER_TENSION_MOMENTUM {φ}{∞}"
        ]
        
        # Use phi_rate to deterministically select a sigil
        idx = int(state * len(sigil_states)) % len(sigil_states)
        return f"Ω Emergence: {sigil_states[idx]}"
