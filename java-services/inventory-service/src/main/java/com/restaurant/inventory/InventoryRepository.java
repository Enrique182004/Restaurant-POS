package com.restaurant.inventory;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.List;

@Repository
public interface InventoryRepository extends JpaRepository<InventoryItem, Long> {
    List<InventoryItem> findByQuantityLessThanEqual(Integer threshold);
    InventoryItem findByName(String name);
}