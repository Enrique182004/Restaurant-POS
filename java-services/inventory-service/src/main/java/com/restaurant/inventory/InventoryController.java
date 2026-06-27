package com.restaurant.inventory;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.List;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/api/inventory")
@CrossOrigin(origins = "http://localhost:5001")
public class InventoryController {
    
    @Autowired
    private InventoryRepository repository;
    
    @GetMapping
    public List<InventoryItem> getAllItems() {
        return repository.findAll();
    }
    
    @GetMapping("/low-stock")
    public List<InventoryItem> getLowStockItems() {
        return repository.findAll().stream()
                .filter(InventoryItem::isLowStock)
                .collect(Collectors.toList());
    }
    
    @GetMapping("/{id}")
    public ResponseEntity<InventoryItem> getItem(@PathVariable Long id) {
        return repository.findById(id)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }
    
    @PostMapping
    public InventoryItem createItem(@RequestBody InventoryItem item) {
        return repository.save(item);
    }
    
    @PutMapping("/{id}")
    public ResponseEntity<InventoryItem> updateItem(
            @PathVariable Long id, 
            @RequestBody InventoryItem itemDetails) {
        
        return repository.findById(id)
                .map(item -> {
                    item.setName(itemDetails.getName());
                    item.setQuantity(itemDetails.getQuantity());
                    item.setMinThreshold(itemDetails.getMinThreshold());
                    item.setUnit(itemDetails.getUnit());
                    return ResponseEntity.ok(repository.save(item));
                })
                .orElse(ResponseEntity.notFound().build());
    }

    @DeleteMapping("/{id}")
public ResponseEntity<Void> deleteItem(@PathVariable Long id) {
    if (repository.existsById(id)) {
        repository.deleteById(id);
        return ResponseEntity.ok().build();
    }
    return ResponseEntity.notFound().build();
}
    
    @PostMapping("/deduct")
    public ResponseEntity<String> deductIngredients(@RequestBody OrderRequest order) {
        // Deduct ingredients based on order items
        for (String ingredient : order.getIngredients()) {
            InventoryItem item = repository.findByName(ingredient);
            if (item != null && item.getQuantity() > 0) {
                item.setQuantity(item.getQuantity() - 1);
                repository.save(item);
            }
        }
        return ResponseEntity.ok("Ingredients deducted successfully");
    }
}

class OrderRequest {
    private List<String> ingredients;
    
    public List<String> getIngredients() { return ingredients; }
    public void setIngredients(List<String> ingredients) { this.ingredients = ingredients; }
}