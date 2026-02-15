// Ring buffer approach for monitor data
// Sends last N iterations, not the whole history

#include <conduit.hpp>
#include <vector>
#include <cstring>

class MonitorRingBuffer {
public:
    static constexpr size_t BUFFER_SIZE = 1000;  // Last 1000 iterations
    
    float iterations[BUFFER_SIZE];
    float residual_continuity[BUFFER_SIZE];
    float residual_momentum[BUFFER_SIZE];
    float residual_energy[BUFFER_SIZE];
    float drag[BUFFER_SIZE];
    float lift[BUFFER_SIZE];
    
    size_t head = 0;      // Next write position
    size_t count = 0;     // Number of valid entries
    
    void append(int iter, float res_cont, float res_mom, float res_e, float cd, float cl) {
        iterations[head] = static_cast<float>(iter);
        residual_continuity[head] = res_cont;
        residual_momentum[head] = res_mom;
        residual_energy[head] = res_e;
        drag[head] = cd;
        lift[head] = cl;
        
        head = (head + 1) % BUFFER_SIZE;
        if (count < BUFFER_SIZE) count++;
    }
    
    // Get contiguous arrays for Conduit (may need to copy if wrapped)
    void get_arrays(std::vector<float>& out_iter,
                    std::vector<float>& out_res_cont,
                    std::vector<float>& out_res_mom,
                    std::vector<float>& out_res_e,
                    std::vector<float>& out_drag,
                    std::vector<float>& out_lift) {
        out_iter.resize(count);
        out_res_cont.resize(count);
        out_res_mom.resize(count);
        out_res_e.resize(count);
        out_drag.resize(count);
        out_lift.resize(count);
        
        if (count < BUFFER_SIZE) {
            // Buffer hasn't wrapped yet - simple copy
            std::memcpy(out_iter.data(), iterations, count * sizeof(float));
            std::memcpy(out_res_cont.data(), residual_continuity, count * sizeof(float));
            std::memcpy(out_res_mom.data(), residual_momentum, count * sizeof(float));
            std::memcpy(out_res_e.data(), residual_energy, count * sizeof(float));
            std::memcpy(out_drag.data(), drag, count * sizeof(float));
            std::memcpy(out_lift.data(), lift, count * sizeof(float));
        } else {
            // Buffer has wrapped - need to copy in order
            size_t start = head;  // Oldest entry
            size_t first_part = BUFFER_SIZE - start;
            
            // Copy from start to end of array
            std::memcpy(out_iter.data(), &iterations[start], first_part * sizeof(float));
            std::memcpy(out_res_cont.data(), &residual_continuity[start], first_part * sizeof(float));
            // ... etc
            
            // Copy from beginning to head
            std::memcpy(&out_iter[first_part], iterations, start * sizeof(float));
            std::memcpy(&out_res_cont[first_part], residual_continuity, start * sizeof(float));
            // ... etc
        }
    }
};

// Usage:
// MonitorRingBuffer monitors;
//
// void coprocess(int iter, Solver* solver) {
//     monitors.append(iter, solver->res_cont, solver->res_mom, ...);
//     
//     std::vector<float> iter_arr, res_cont_arr, ...;
//     monitors.get_arrays(iter_arr, res_cont_arr, ...);
//     
//     conduit::Node node;
//     node["catalyst/channels/monitors/data/coordsets/coords/values/x"].set(iter_arr);
//     node["catalyst/channels/monitors/data/fields/continuity/values"].set(res_cont_arr);
//     // ... rest of Blueprint setup
//     
//     catalyst_execute(conduit::c_node(&node));
// }
